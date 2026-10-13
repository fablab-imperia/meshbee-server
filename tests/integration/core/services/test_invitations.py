"""Apiary invitations by email (#55): meshbee_core/services/invitations.py.

Over `inviti_apiari` (the pending shares, #40) and `token_monouso` (the emailed
links). Everything runs in one rolled-back transaction, where `now()` does not
move: a token is made expired by issuing it with a negative lifetime.
"""

from datetime import timedelta

import pytest

from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.models import CondivisioneCreate
from meshbee_core.repository import accessi as accessi_repo
from meshbee_core.repository import token_monouso
from meshbee_core.security import hash_token
from meshbee_core.services import accessi, invitations

LIFETIME = timedelta(days=7)
CAP = 3
EMAIL = "new@example.org"


@pytest.fixture
def owner(make_utente):
    return make_utente()


@pytest.fixture
def apiario(make_apiario, owner):
    return make_apiario(owner)


def share(
    session, apiario, owner, email=EMAIL, ruolo="viewer", lifetime=LIFETIME, cap=CAP
):
    return invitations.share(
        session,
        apiario["id_apiario"],
        CondivisioneCreate(email=email, ruolo=ruolo),
        id_mittente=owner["id_utente"],
        invite_lifetime=lifetime,
        max_per_day=cap,
    )


def accept(session, token, password="secret123"):
    return invitations.accept(session, token, "Nuovo", "Utente", password)


def tokens(db, email=EMAIL):
    db.execute(
        "SELECT * FROM token_monouso WHERE email = %s ORDER BY id_token", (email,)
    )
    return db.fetchall()


def pending_invito(db, apiario, email=EMAIL):
    db.execute(
        "SELECT id_invito FROM inviti_apiari WHERE email = %s AND id_apiario = %s",
        (email, apiario["id_apiario"]),
    )
    return db.fetchone()["id_invito"]


# ============================================
# Sharing
# ============================================


def test_an_unknown_email_gets_an_invitation_token(session, db, apiario, owner):
    result = share(session, apiario, owner)

    assert result["stato"] == "in_attesa"
    assert result["nome_apiario"] == apiario["nome_apiario"]
    (row,) = tokens(db)
    assert row["token_hash"] == hash_token(result["token"])
    assert row["scopo"] == "invite"
    assert row["id_utente"] is None
    assert row["id_mittente"] == owner["id_utente"]
    assert row["data_scadenza"] - row["data_creazione"] == LIFETIME


def test_an_existing_account_gets_no_token(session, db, apiario, owner, make_utente):
    guest = make_utente()

    result = share(session, apiario, owner, email=guest["email"])

    assert (result["stato"], result["token"]) == ("attiva", None)
    assert tokens(db, guest["email"]) == []


def test_without_email_no_token_is_issued(session, db, apiario, owner):
    result = share(session, apiario, owner, lifetime=None)

    assert (result["stato"], result["token"]) == ("in_attesa", None)
    assert tokens(db) == []


def test_inviting_again_replaces_the_link(session, db, apiario, owner):
    first = share(session, apiario, owner)["token"]
    second = share(session, apiario, owner, ruolo="manager")["token"]

    old, new = tokens(db)
    assert old["data_utilizzo"] is not None
    assert new["data_utilizzo"] is None
    with pytest.raises(InvalidData):
        accept(session, first)
    accept(session, second)


def test_the_sender_cap_stops_the_emails_but_not_the_invitations(
    session, db, apiario, owner
):
    """Past the cap the invitation is still stored (#40's answer must not change)."""
    for i in range(CAP):
        assert share(session, apiario, owner, email=f"n{i}@example.org")["token"]

    result = share(session, apiario, owner, email="late@example.org")

    assert (result["stato"], result["token"]) == ("in_attesa", None)
    assert pending_invito(db, apiario, "late@example.org")


def test_the_cap_is_per_sender(session, apiario, owner, make_utente, make_apiario):
    other = make_utente()
    for i in range(CAP):
        share(session, apiario, owner, email=f"n{i}@example.org")

    assert share(session, make_apiario(other), other)["token"]


# ============================================
# Resending
# ============================================


def test_resending_issues_a_new_link_and_spends_the_old(session, db, apiario, owner):
    old = share(session, apiario, owner)["token"]

    result = invitations.resend(
        session,
        apiario["id_apiario"],
        pending_invito(db, apiario),
        owner["id_utente"],
        LIFETIME,
        CAP,
    )

    assert result["email"] == EMAIL
    assert result["nome_apiario"] == apiario["nome_apiario"]
    with pytest.raises(InvalidData):
        accept(session, old)
    accept(session, result["token"])


def test_resending_counts_towards_the_cap(session, db, apiario, owner):
    share(session, apiario, owner)
    id_invito = pending_invito(db, apiario)
    for _ in range(CAP - 1):
        invitations.resend(
            session, apiario["id_apiario"], id_invito, owner["id_utente"], LIFETIME, CAP
        )

    assert (
        invitations.resend(
            session, apiario["id_apiario"], id_invito, owner["id_utente"], LIFETIME, CAP
        )
        is None
    )


def test_resending_needs_an_invitation_of_that_apiary(
    session, db, apiario, owner, make_apiario
):
    share(session, apiario, owner)
    other = make_apiario(owner)

    with pytest.raises(NotFound):
        invitations.resend(
            session,
            other["id_apiario"],
            pending_invito(db, apiario),
            owner["id_utente"],
            LIFETIME,
            CAP,
        )


# ============================================
# Accepting
# ============================================


def test_accepting_creates_the_account_with_every_invitation(
    session, db, apiario, owner, make_utente, make_apiario
):
    other_owner = make_utente()
    other = make_apiario(other_owner)
    token = share(session, apiario, owner, ruolo="collaborator")["token"]
    share(session, other, other_owner, ruolo="manager", lifetime=None)

    user = accept(session, token)

    assert (user["email"], user["ruolo"], user["nome"]) == (EMAIL, "user", "Nuovo")
    assert "password_hash" not in user
    access = accessi_repo.accesso_su_apiario
    assert access(session, user["id_utente"], apiario["id_apiario"]) == "collaborator"
    assert access(session, user["id_utente"], other["id_apiario"]) == "manager"
    db.execute("SELECT count(*) AS n FROM inviti_apiari")
    assert db.fetchone()["n"] == 0
    assert all(row["data_utilizzo"] is not None for row in tokens(db))


def test_a_link_works_once(session, apiario, owner):
    token = share(session, apiario, owner)["token"]
    accept(session, token)

    with pytest.raises(InvalidData) as exc_info:
        accept(session, token)

    assert str(exc_info.value) == invitations.INVALID_LINK


def test_an_expired_link_is_refused(session, apiario, owner):
    token = share(session, apiario, owner, lifetime=timedelta(minutes=-1))["token"]

    with pytest.raises(InvalidData):
        accept(session, token)


def test_an_unknown_link_is_refused(session):
    with pytest.raises(InvalidData):
        accept(session, "never-issued")


def test_withdrawing_the_last_invitation_voids_the_link(session, db, apiario, owner):
    token = share(session, apiario, owner)["token"]

    accessi.revoke_invito(session, apiario["id_apiario"], pending_invito(db, apiario))

    with pytest.raises(InvalidData):
        accept(session, token)


def test_withdrawing_one_of_several_invitations_keeps_the_link(
    session, db, apiario, owner, make_apiario
):
    """The link still has an apiary to accept; the withdrawn one is simply not in it."""
    other = make_apiario(owner)
    share(session, other, owner)
    token = share(session, apiario, owner)["token"]

    accessi.revoke_invito(session, other["id_apiario"], pending_invito(db, other))
    user = accept(session, token)

    access = accessi_repo.accesso_su_apiario
    assert access(session, user["id_utente"], apiario["id_apiario"]) == "viewer"
    assert access(session, user["id_utente"], other["id_apiario"]) is None


def test_an_address_that_got_an_account_meanwhile_is_refused(
    session, apiario, owner, make_utente
):
    """An admin created it since: the link must not make a second one, nor log into it."""
    token = share(session, apiario, owner)["token"]
    make_utente(email=EMAIL)

    with pytest.raises(InvalidData):
        accept(session, token)


def test_a_malformed_invited_address_is_one_more_invalid_link(session):
    """
    Sharing no longer accepts one, but a row from before must not reach a 500.

    No account could ever have the address, so the link is simply invalid.
    """
    token_monouso.insert(
        session, "invite", hash_token("odd"), LIFETIME, email="not-an-email"
    )

    with pytest.raises(InvalidData) as exc_info:
        accept(session, "odd")

    assert str(exc_info.value) == invitations.INVALID_LINK
