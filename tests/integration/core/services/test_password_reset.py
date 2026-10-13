"""Password reset by email (#54): meshbee_core/services/password_reset.py over token_monouso.

Everything runs in one rolled-back transaction, where `now()` does not move: a
token is made expired by issuing it with a negative lifetime, and old by
back-dating its row.
"""

from datetime import timedelta

import bcrypt
import pytest

from meshbee_core.errors import InvalidData
from meshbee_core.repository import token_monouso
from meshbee_core.security import hash_token
from meshbee_core.services import auth
from meshbee_core.services import password_reset as service

LIFETIME = timedelta(minutes=30)
CAP = 3
NEW_PASSWORD = "una-nuova-password"


@pytest.fixture
def utente(make_utente):
    return make_utente()


def request(session, email, cap=CAP, lifetime=LIFETIME):
    return service.request_reset(session, email, lifetime=lifetime, max_per_window=cap)


def rows(db, id_utente):
    db.execute(
        "SELECT * FROM token_monouso WHERE id_utente = %s ORDER BY id_token",
        (id_utente,),
    )
    return db.fetchall()


def stored_hash(db, id_utente):
    db.execute("SELECT password_hash FROM utenti WHERE id_utente = %s", (id_utente,))
    return db.fetchone()["password_hash"]


# ============================================
# Requesting a reset
# ============================================


def test_a_request_stores_the_hash_never_the_token(session, db, utente):
    user, token = request(session, utente["email"])

    assert user["id_utente"] == utente["id_utente"]
    assert "password_hash" not in user
    (row,) = rows(db, utente["id_utente"])
    assert row["token_hash"] == hash_token(token)
    assert row["email"] == utente["email"]
    assert row["id_mittente"] is None
    assert token not in row["token_hash"]
    assert row["scopo"] == "password_reset"
    assert row["data_utilizzo"] is None
    assert row["data_scadenza"] - row["data_creazione"] == LIFETIME


def test_tokens_are_long_and_random(session, utente):
    _, first = request(session, utente["email"])
    _, second = request(session, utente["email"])

    assert first != second
    assert len(first) >= 43  # 32 random bytes, base64url


def test_an_unknown_email_gets_nothing(session, db):
    assert request(session, "nobody@example.org") is None
    db.execute("SELECT count(*) AS n FROM token_monouso")
    assert db.fetchone()["n"] == 0


def test_a_deactivated_account_gets_nothing(session, db, make_utente):
    utente = make_utente(attivo=False)

    assert request(session, utente["email"]) is None
    assert rows(db, utente["id_utente"]) == []


def test_a_new_request_spends_the_earlier_unused_token(session, db, utente):
    _, old = request(session, utente["email"])
    _, new = request(session, utente["email"])

    first, second = rows(db, utente["id_utente"])
    assert first["data_utilizzo"] is not None
    assert second["data_utilizzo"] is None
    with pytest.raises(InvalidData):
        service.reset_password(session, old, NEW_PASSWORD)
    service.reset_password(session, new, NEW_PASSWORD)


def test_the_per_account_cap_stops_further_requests(session, db, utente):
    """The cap counts every token issued within the hour, spent or not."""
    for _ in range(CAP):
        assert request(session, utente["email"]) is not None

    assert request(session, utente["email"]) is None
    assert len(rows(db, utente["id_utente"])) == CAP


def test_the_cap_is_per_account(session, utente, make_utente):
    other = make_utente()
    for _ in range(CAP):
        request(session, utente["email"])

    assert request(session, other["email"]) is not None


def test_requests_older_than_the_window_do_not_count(session, db, utente):
    for _ in range(CAP):
        request(session, utente["email"])
    db.execute(
        "UPDATE token_monouso SET data_creazione = data_creazione - interval '2 hours' "
        "WHERE id_utente = %s",
        (utente["id_utente"],),
    )

    assert request(session, utente["email"]) is not None


def back_date(db, id_utente, interval):
    db.execute(
        "UPDATE token_monouso SET data_creazione = data_creazione - %s::interval, "
        "data_scadenza = data_scadenza - %s::interval WHERE id_utente = %s",
        (interval, interval, id_utente),
    )


def test_rows_expired_past_retention_are_deleted_on_the_next_request(
    session, db, utente, make_utente
):
    """Any user's: the sweep keeps the whole table small, not just the requester's rows."""
    other = make_utente()
    request(session, utente["email"])
    request(session, other["email"])
    back_date(db, utente["id_utente"], "2 days")
    back_date(db, other["id_utente"], "2 days")

    request(session, utente["email"])

    (row,) = rows(db, utente["id_utente"])
    assert row["data_utilizzo"] is None
    assert rows(db, other["id_utente"]) == []


def test_a_live_invitation_survives_the_sweep(session, db, utente):
    """Retention follows expiry, so a week-long invitation (#55) is not swept after a day."""
    token_monouso.insert(
        session, "invite", hash_token("inv"), timedelta(days=7), email="new@example.org"
    )
    db.execute(
        "UPDATE token_monouso SET data_creazione = data_creazione - interval '3 days' "
        "WHERE email = 'new@example.org'"
    )

    request(session, utente["email"])

    spent = token_monouso.spend(session, "invite", hash_token("inv"))
    assert spent == {"id_utente": None, "email": "new@example.org", "id_mittente": None}


def test_a_reset_token_must_belong_to_an_account(session):
    """Only an invitation may go to an address with no account behind it."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="token_monouso_utente_check"):
        token_monouso.insert(
            session, "password_reset", hash_token("x"), LIFETIME, email="a@example.org"
        )


# ============================================
# Resetting with a token
# ============================================


def test_a_valid_token_sets_the_new_password(session, db, utente):
    _, token = request(session, utente["email"])

    user = service.reset_password(session, token, NEW_PASSWORD)

    assert user["email"] == utente["email"]
    hashed = stored_hash(db, utente["id_utente"])
    assert bcrypt.checkpw(NEW_PASSWORD.encode(), hashed.encode())


def test_a_token_works_once(session, utente):
    _, token = request(session, utente["email"])
    service.reset_password(session, token, NEW_PASSWORD)

    with pytest.raises(InvalidData) as exc_info:
        service.reset_password(session, token, "ancora-un-altra")

    assert str(exc_info.value) == service.INVALID_LINK


def test_an_expired_token_is_refused(session, db, utente):
    _, token = request(session, utente["email"], lifetime=timedelta(minutes=-1))
    before = stored_hash(db, utente["id_utente"])

    with pytest.raises(InvalidData) as exc_info:
        service.reset_password(session, token, NEW_PASSWORD)

    assert str(exc_info.value) == service.INVALID_LINK
    assert stored_hash(db, utente["id_utente"]) == before


def test_an_unknown_token_is_refused(session):
    with pytest.raises(InvalidData) as exc_info:
        service.reset_password(session, "never-issued", NEW_PASSWORD)

    assert str(exc_info.value) == service.INVALID_LINK


def test_an_account_deactivated_since_the_request_is_refused(session, db, utente):
    _, token = request(session, utente["email"])
    db.execute(
        "UPDATE utenti SET attivo = false WHERE id_utente = %s", (utente["id_utente"],)
    )

    with pytest.raises(InvalidData) as exc_info:
        service.reset_password(session, token, NEW_PASSWORD)

    assert str(exc_info.value) == service.INVALID_LINK


def test_a_reset_token_cannot_be_used_as_another_purpose(session, utente):
    """`spend` matches the purpose too, so a reset token is no invitation."""
    _, token = request(session, utente["email"])

    assert token_monouso.spend(session, "invite", hash_token(token)) is None


def test_a_reset_logs_out_every_session(session, db, utente):
    """A new password ends every refresh token, as the other password routes do."""
    auth.open_session(session, utente["id_utente"], "refresh-1", 7)
    _, token = request(session, utente["email"])

    service.reset_password(session, token, NEW_PASSWORD)

    assert auth.redeem_refresh_token(session, "refresh-1") is None
