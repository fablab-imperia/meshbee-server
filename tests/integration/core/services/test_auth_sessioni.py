"""Refresh-token sessions (#16): meshbee_core/services/auth.py over token_sessione.

The token strings here are opaque: the service hashes whatever it is given, and
checking that a string is a well-signed JWT is the API's job.
"""

import pytest

from meshbee_core.models import UserUpdate
from meshbee_core.repository import sessioni
from meshbee_core.security import hash_token
from meshbee_core.services import auth, utenti


@pytest.fixture
def utente(make_utente):
    return make_utente()


def rows(db, id_utente):
    db.execute(
        "SELECT * FROM token_sessione WHERE id_utente = %s ORDER BY id_token",
        (id_utente,),
    )
    return db.fetchall()


def test_a_session_stores_the_hash_never_the_token(session, db, utente):
    auth.open_session(
        session, utente["id_utente"], "tok-1", 7, ip_address="10.0.0.1", user_agent="UA"
    )

    (row,) = rows(db, utente["id_utente"])
    assert row["refresh_token"] == hash_token("tok-1")
    assert "tok-1" not in row["refresh_token"]
    assert row["revocato"] is False
    assert row["ip_address"] == "10.0.0.1"
    assert row["user_agent"] == "UA"
    assert row["data_scadenza"] > row["data_creazione"]


def test_redeeming_spends_the_token_and_returns_the_user(session, db, utente):
    auth.open_session(session, utente["id_utente"], "tok-1", 7)

    user = auth.redeem_refresh_token(session, "tok-1")

    assert user["id_utente"] == utente["id_utente"]
    assert "password_hash" not in user
    assert rows(db, utente["id_utente"])[0]["revocato"] is True


def test_an_unknown_token_redeems_nothing(session, utente):
    assert auth.redeem_refresh_token(session, "never-issued") is None


def test_an_expired_token_redeems_nothing(session, db, utente):
    sessioni.insert(session, utente["id_utente"], hash_token("old"), -1)

    assert auth.redeem_refresh_token(session, "old") is None


def test_a_disabled_account_redeems_nothing(session, make_utente):
    inactive = make_utente(attivo=False)
    auth.open_session(session, inactive["id_utente"], "tok-1", 7)

    assert auth.redeem_refresh_token(session, "tok-1") is None


def test_reusing_a_spent_token_revokes_every_session_of_the_user(session, db, utente):
    """A spent token coming back was copied: the thief and the owner both lose."""
    auth.open_session(session, utente["id_utente"], "tok-1", 7)
    auth.redeem_refresh_token(session, "tok-1")
    auth.open_session(session, utente["id_utente"], "tok-2", 7)

    assert auth.redeem_refresh_token(session, "tok-1") is None

    assert all(row["revocato"] for row in rows(db, utente["id_utente"]))
    assert auth.redeem_refresh_token(session, "tok-2") is None


def test_reuse_detection_spares_other_users(session, db, make_utente):
    thief_target, bystander = make_utente(), make_utente()
    auth.open_session(session, thief_target["id_utente"], "tok-1", 7)
    auth.open_session(session, bystander["id_utente"], "tok-b", 7)
    auth.redeem_refresh_token(session, "tok-1")

    auth.redeem_refresh_token(session, "tok-1")

    assert (
        auth.redeem_refresh_token(session, "tok-b")["id_utente"]
        == (bystander["id_utente"])
    )


def test_closing_a_session_revokes_only_that_token(session, db, utente):
    auth.open_session(session, utente["id_utente"], "phone", 7)
    auth.open_session(session, utente["id_utente"], "tablet", 7)

    auth.close_session(session, "phone")

    phone, tablet = rows(db, utente["id_utente"])
    assert phone["revocato"] is True
    assert tablet["revocato"] is False


def test_closing_an_unknown_session_is_silent(session, utente):
    auth.close_session(session, "never-issued")


def test_a_new_session_prunes_expired_ones_but_keeps_revoked_ones(session, db, utente):
    """Revoked rows that have not expired are what detects a reused token."""
    sessioni.insert(session, utente["id_utente"], hash_token("expired"), -1)
    auth.open_session(session, utente["id_utente"], "spent", 7)
    auth.redeem_refresh_token(session, "spent")

    auth.open_session(session, utente["id_utente"], "fresh", 7)

    stored = {row["refresh_token"] for row in rows(db, utente["id_utente"])}
    assert stored == {hash_token("spent"), hash_token("fresh")}


# ============================================
# What else revokes: services/utenti.py
# ============================================


@pytest.fixture
def logged_in(session, make_utente):
    def _make(**kwargs):
        user = make_utente(**kwargs)
        auth.open_session(session, user["id_utente"], f"tok-{user['id_utente']}", 7)
        return user, f"tok-{user['id_utente']}"

    return _make


def test_deactivating_a_user_revokes_their_sessions(session, make_utente, logged_in):
    admin = make_utente(ruolo="admin")
    user, token = logged_in()

    utenti.deactivate_utente(
        session, user["id_utente"], acting_user_id=admin["id_utente"]
    )

    assert sessioni.get_by_hash(session, hash_token(token))["revocato"] is True


def test_updating_a_user_to_inactive_revokes_their_sessions(session, logged_in):
    user, token = logged_in()

    utenti.update_utente(session, user["id_utente"], UserUpdate(attivo=False))

    assert sessioni.get_by_hash(session, hash_token(token))["revocato"] is True


def test_other_updates_leave_sessions_alone(session, logged_in):
    user, token = logged_in()

    utenti.update_utente(session, user["id_utente"], UserUpdate(nome="Nuovo"))

    assert sessioni.get_by_hash(session, hash_token(token))["revocato"] is False


def test_an_admin_password_reset_revokes_the_users_sessions(session, logged_in):
    user, token = logged_in()

    utenti.reset_password(session, user["id_utente"], "a-new-password")

    assert sessioni.get_by_hash(session, hash_token(token))["revocato"] is True


def test_changing_your_own_password_revokes_your_sessions(
    session, logged_in, password_hash, known_password
):
    user, token = logged_in(password_hash=password_hash)

    utenti.change_own_password(
        session, user["id_utente"], known_password, "a-new-password"
    )

    assert sessioni.get_by_hash(session, hash_token(token))["revocato"] is True


def test_revoking_reports_whether_this_call_spent_the_token(session, utente):
    row = sessioni.insert(session, utente["id_utente"], hash_token("tok-1"), 7)

    assert sessioni.revoke(session, row["id_token"]) is True
    assert sessioni.revoke(session, row["id_token"]) is False


def test_a_redeem_that_loses_the_race_counts_as_reuse(session, db, utente, monkeypatch):
    """
    Two concurrent refreshes with one token both read it as live. Only the
    conditional revoke can tell them apart: the loser must get nothing, and
    every session of the account ends, as for any other reuse.
    """
    auth.open_session(session, utente["id_utente"], "tok-1", 7)
    auth.open_session(session, utente["id_utente"], "tok-other", 7)
    stale = sessioni.get_by_hash(session, hash_token("tok-1"))
    auth.redeem_refresh_token(session, "tok-1")  # the winner
    monkeypatch.setattr(sessioni, "get_by_hash", lambda *_: stale)

    assert auth.redeem_refresh_token(session, "tok-1") is None

    assert all(row["revocato"] for row in rows(db, utente["id_utente"]))
