"""Tests for the apiari repository (meshbee_core/repository/apiari.py).

An apiary belongs to one user and holds that user's hives; others reach it
only through a share. The weight is on what a user's list contains, with what
access, and on what counts as "still holding hives" when deleting.
"""

import psycopg
import pytest

from meshbee_core.repository import apiari


def test_a_user_lists_their_own_apiari_then_those_shared_with_them(
    session, make_utente, make_apiario, share
):
    utente, other = make_utente(), make_utente()
    mine = make_apiario(utente, nome_apiario="Alpha")
    theirs = make_apiario(other)
    make_apiario(other)  # not shared
    share(utente["id_utente"], theirs["id_apiario"], "viewer")

    rows = apiari.list_for_utente(session, utente["id_utente"])

    assert [(a["id_apiario"], a["accesso"]) for a in rows] == [
        (utente["id_apiario_predefinito"], "owner"),
        (mine["id_apiario"], "owner"),
        (theirs["id_apiario"], "viewer"),
    ]


def test_one_apiario_comes_with_the_users_access(session, make_utente, make_apiario):
    """An admin who neither owns nor has it shared still finds it, with no access."""
    owner, admin = make_utente(), make_utente(ruolo="admin")
    apiario = make_apiario(owner)

    as_owner = apiari.get_for_utente(session, apiario["id_apiario"], owner["id_utente"])
    as_admin = apiari.get_for_utente(session, apiario["id_apiario"], admin["id_utente"])

    assert as_owner["accesso"] == "owner"
    assert as_admin["accesso"] is None


def test_the_default_is_found(session, make_utente):
    utente = make_utente()

    found = apiari.get_predefinito(session, utente["id_utente"])

    assert found["id_apiario"] == utente["id_apiario_predefinito"]


def test_a_user_cannot_have_two_defaults(db, make_utente):
    """The partial unique index is what keeps "the default" well defined."""
    utente = make_utente()

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO apiari (nome_apiario, id_utente_proprietario, predefinito)"
            " VALUES ('Second', %s, true)",
            (utente["id_utente"],),
        )


def test_only_active_hives_are_counted(
    session, db, make_utente, make_apiario, make_arnia
):
    """Retired hives no longer block deleting their apiary."""
    utente = make_utente()
    apiario = make_apiario(utente)
    make_arnia(apiario=apiario)
    retired = make_arnia(apiario=apiario)
    make_arnia(apiario=utente)
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (retired["id_arnia"],)
    )

    assert apiari.count_arnie_attive(session, apiario["id_apiario"]) == 1


def test_update_leaves_unmentioned_columns_alone(session, make_utente, make_apiario):
    apiario = make_apiario(make_utente(), nome_apiario="Collina")

    updated = apiari.update(
        session, apiario["id_apiario"], posizione="Collina sud", nome_apiario=None
    )

    assert updated["nome_apiario"] == "Collina"
    assert updated["posizione"] == "Collina sud"


def test_deleting_an_apiario_deletes_its_shares(
    session, db, make_utente, make_apiario, share
):
    """ON DELETE CASCADE on `utenti_apiari`: a share of nothing means nothing."""
    utente = make_utente()
    apiario = make_apiario(make_utente())
    share(utente["id_utente"], apiario["id_apiario"], "viewer")

    apiari.delete(session, apiario["id_apiario"])

    db.execute("SELECT count(*) AS n FROM utenti_apiari")
    assert db.fetchone()["n"] == 0
