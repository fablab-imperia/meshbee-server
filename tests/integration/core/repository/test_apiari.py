"""Tests for the apiari repository (meshbee_core/repository/apiari.py).

Apiaries are personal, and which one a hive is in lives on the association.
The weight is on what counts as "a hive in it": that is the rule that decides
whether an apiary can be deleted.
"""

import psycopg2
import pytest

from meshbee_core.repository import apiari


def test_a_users_list_holds_only_their_apiari_default_first(
    session, make_utente, make_apiario
):
    utente, other = make_utente(), make_utente()
    extra = make_apiario(utente, nome_apiario="Alpha")
    make_apiario(other)

    ids = [a["id_apiario"] for a in apiari.list_all(session, utente["id_utente"])]

    assert ids == [utente["id_apiario_predefinito"], extra["id_apiario"]]


def test_the_default_is_found(session, make_utente):
    utente = make_utente()

    found = apiari.get_predefinito(session, utente["id_utente"])

    assert found["id_apiario"] == utente["id_apiario_predefinito"]


def test_a_user_cannot_have_two_defaults(db, make_utente):
    """The partial unique index is what keeps "the default" well defined."""
    utente = make_utente()

    with pytest.raises(psycopg2.errors.UniqueViolation):
        db.execute(
            "INSERT INTO apiari (nome_apiario, id_utente_proprietario, predefinito)"
            " VALUES ('Second', %s, true)",
            (utente["id_utente"],),
        )


def test_a_hive_cannot_go_in_someone_elses_apiario(
    db, make_utente, make_apiario, make_arnia, grant_access
):
    """The composite foreign key: the database itself refuses a cross-user placement."""
    utente, other = make_utente(), make_utente()
    theirs = make_apiario(other)

    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        grant_access(
            utente["id_utente"],
            make_arnia()["id_arnia"],
            id_apiario=theirs["id_apiario"],
        )


def test_only_active_associations_with_active_hives_are_counted(
    session, db, make_utente, make_apiario, make_arnia, grant_access
):
    utente = make_utente()
    apiario = make_apiario(utente)
    for attivo in (True, False):
        grant_access(
            utente["id_utente"],
            make_arnia()["id_arnia"],
            attivo=attivo,
            id_apiario=apiario["id_apiario"],
        )
    retired = make_arnia()
    grant_access(
        utente["id_utente"], retired["id_arnia"], id_apiario=apiario["id_apiario"]
    )
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


def test_deleting_the_user_deletes_their_apiari(session, db, make_utente):
    """ON DELETE CASCADE: personal groupings mean nothing without their owner."""
    utente = make_utente()

    db.execute("DELETE FROM utenti WHERE id_utente = %s", (utente["id_utente"],))

    assert apiari.get(session, utente["id_apiario_predefinito"]) is None
