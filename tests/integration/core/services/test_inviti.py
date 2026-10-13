"""Pending invitations (#40): meshbee_core/services/accessi.py over inviti_apiari.

The routes are covered in tests/integration/api/test_main_user_apiari.py; these
pin when an invitation turns into a share, and when it must not.
"""

from meshbee_core.models import CondivisioneCreate, UserCreate, UserUpdate
from meshbee_core.repository import accessi as accessi_repo
from meshbee_core.services import accessi, utenti


def invite(session, apiario, email, ruolo="viewer"):
    return accessi.share(
        session, apiario["id_apiario"], CondivisioneCreate(email=email, ruolo=ruolo)
    )


def pending(db):
    db.execute("SELECT email, id_apiario, ruolo FROM inviti_apiari ORDER BY id_invito")
    return [tuple(row.values()) for row in db.fetchall()]


def test_an_unknown_email_is_invited_and_told_apart_only_internally(
    session, make_utente, make_apiario
):
    apiario = make_apiario(make_utente())

    result = invite(session, apiario, "new@example.org")

    assert result["stato"] == "in_attesa"
    assert isinstance(result["id_invito"], int)


def test_a_known_email_is_shared_at_once(session, make_utente, make_apiario):
    guest = make_utente()
    apiario = make_apiario(make_utente())

    result = invite(session, apiario, guest["email"])

    assert (result["stato"], result["id_utente"]) == ("attiva", guest["id_utente"])


def test_creating_the_account_turns_every_invitation_into_a_share(
    session, db, make_utente, make_apiario
):
    first, second = make_apiario(make_utente()), make_apiario(make_utente())
    invite(session, first, "new@example.org", "viewer")
    invite(session, second, "new@example.org", "manager")
    invite(session, second, "someone-else@example.org")

    created = utenti.create_utente(
        session,
        UserCreate(
            email="new@example.org", nome="N", cognome="C", password="secret123"
        ),
    )

    id_utente = created["id_utente"]
    assert (
        accessi_repo.accesso_su_apiario(session, id_utente, first["id_apiario"])
        == "viewer"
    )
    assert (
        accessi_repo.accesso_su_apiario(session, id_utente, second["id_apiario"])
        == "manager"
    )
    assert pending(db) == [("someone-else@example.org", second["id_apiario"], "viewer")]


def test_taking_on_an_invited_email_receives_its_invitations(
    session, db, make_utente, make_apiario
):
    """No account will ever be created with that email now, so this one gets them."""
    apiario = make_apiario(make_utente())
    utente = make_utente()
    invite(session, apiario, "new@example.org", "collaborator")

    utenti.update_utente(
        session, utente["id_utente"], UserUpdate(email="new@example.org")
    )

    access = accessi_repo.accesso_su_apiario(
        session, utente["id_utente"], apiario["id_apiario"]
    )
    assert access == "collaborator"
    assert pending(db) == []


def test_an_invitation_to_ones_own_apiary_is_dropped(
    session, db, make_utente, make_apiario
):
    """Owning allows everything; a role on top would only confuse the share list."""
    owner = make_utente()
    apiario = make_apiario(owner)
    invite(session, apiario, "new@example.org")

    utenti.update_utente(
        session, owner["id_utente"], UserUpdate(email="new@example.org")
    )

    assert (
        accessi_repo.accesso_su_apiario(
            session, owner["id_utente"], apiario["id_apiario"]
        )
        == "owner"
    )
    db.execute("SELECT count(*) AS n FROM utenti_apiari")
    assert db.fetchone()["n"] == 0
    assert pending(db) == []


def test_deleting_the_apiary_deletes_its_invitations(
    session, db, make_utente, make_apiario
):
    apiario = make_apiario(make_utente())
    invite(session, apiario, "new@example.org")

    db.execute("DELETE FROM apiari WHERE id_apiario = %s", (apiario["id_apiario"],))

    assert pending(db) == []
