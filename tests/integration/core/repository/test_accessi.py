"""Tests for the accessi repository (meshbee_core/repository/accessi.py).

What a user may do on an apiary or a hive comes down to two lookups: is the
apiary theirs, and what role has its owner shared with them. These pin both
against the real tables.
"""

from meshbee_core.repository import accessi


def test_the_owner_of_an_apiario_is_reported_as_owner(session, make_utente):
    utente = make_utente()

    assert (
        accessi.accesso_su_apiario(
            session, utente["id_utente"], utente["id_apiario_predefinito"]
        )
        == "owner"
    )


def test_a_shared_role_is_reported_on_the_apiario_and_its_hives(
    session, make_utente, make_arnia, share
):
    utente, owner = make_utente(), make_utente()
    arnia = make_arnia(apiario=owner)
    share(utente["id_utente"], arnia["id_apiario"], "collaborator")

    assert (
        accessi.accesso_su_apiario(session, utente["id_utente"], arnia["id_apiario"])
        == "collaborator"
    )
    assert (
        accessi.accesso_su_arnia(session, utente["id_utente"], arnia["id_arnia"])
        == "collaborator"
    )


def test_nothing_is_reported_without_ownership_or_a_share(
    session, make_utente, make_arnia
):
    utente = make_utente()
    arnia = make_arnia(apiario=make_utente())

    assert (
        accessi.accesso_su_arnia(session, utente["id_utente"], arnia["id_arnia"])
        is None
    )


def test_an_unassigned_hive_gives_nobody_access(session, make_utente, make_arnia):
    """No apiary means no owner and no share: only the admin bypass reaches it."""
    arnia = make_arnia()

    assert (
        accessi.accesso_su_arnia(session, make_utente()["id_utente"], arnia["id_arnia"])
        is None
    )


def test_sharing_again_changes_the_role(session, make_utente):
    utente, owner = make_utente(), make_utente()
    apiario = owner["id_apiario_predefinito"]

    accessi.upsert(session, utente["id_utente"], apiario, "viewer")
    accessi.upsert(session, utente["id_utente"], apiario, "manager")

    shares = accessi.list_for_apiario(session, apiario)
    assert [(s["id_utente"], s["ruolo"]) for s in shares] == [
        (utente["id_utente"], "manager")
    ]
    assert shares[0]["email"] == utente["email"]


def test_revoking_removes_the_share(session, make_utente, share):
    utente, owner = make_utente(), make_utente()
    share(utente["id_utente"], owner["id_apiario_predefinito"], "viewer")

    assert accessi.delete_share(
        session, utente["id_utente"], owner["id_apiario_predefinito"]
    )
    assert (
        accessi.accesso_su_apiario(
            session, utente["id_utente"], owner["id_apiario_predefinito"]
        )
        is None
    )
    assert not accessi.delete_share(
        session, utente["id_utente"], owner["id_apiario_predefinito"]
    )
