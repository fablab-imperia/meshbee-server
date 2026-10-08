"""Tests for the ingest service (meshbee_core/services/ingest.py).

`ultimo_messaggio` and where a provisioned hive goes are covered here — the stored row is
the subject of tests/integration/test_ingest_parity.py, through the real MQTT
callback. These pin the two defects of the trigger this service replaced (#17):
the value came from the node's clock, so it could go backwards.
"""

from datetime import datetime

import pytest

from meshbee_core.errors import InvalidData
from meshbee_core.services import ingest, letture


def ultimo_messaggio(db, id_nodo):
    """The node's stamp, and whether it is this transaction's "now"."""
    db.execute(
        "SELECT ultimo_messaggio, ultimo_messaggio = CURRENT_TIMESTAMP AS is_now"
        " FROM nodi WHERE id_nodo = %s",
        (id_nodo,),
    )
    return db.fetchone()


def test_a_message_stamps_the_time_it_was_received(session, db):
    """A node whose clock says 2020 was still heard from now."""
    ingest.record_node_reading(
        session,
        {
            "id_nodo": "NODE-RTC",
            "id_sensore": "S1",
            "timestamp": datetime(2020, 1, 1),
            "temperatura": 20,
        },
    )

    # One transaction, so CURRENT_TIMESTAMP is the instant the UPDATE saw.
    assert ultimo_messaggio(db, "NODE-RTC")["is_now"] is True


def test_an_older_reading_does_not_move_it_backwards(session, db):
    """Replaying buffered readings after an outage must not rewind "last heard"."""
    ingest.record_node_reading(session, {"id_nodo": "NODE-REPLAY", "id_sensore": "S1"})
    first = ultimo_messaggio(db, "NODE-REPLAY")["ultimo_messaggio"]

    ingest.record_node_reading(
        session,
        {
            "id_nodo": "NODE-REPLAY",
            "id_sensore": "S1",
            "timestamp": datetime(2019, 6, 1),
        },
    )

    assert ultimo_messaggio(db, "NODE-REPLAY")["ultimo_messaggio"] >= first


def test_a_refused_reading_stamps_nothing(session, db):
    """The stamp is part of the message's transaction, and rolls back with it."""
    with pytest.raises(InvalidData):
        with (
            session.begin_nested()
        ):  # what a `with get_session()` block is, in production
            ingest.record_node_reading(
                session,
                {
                    "id_nodo": "NODE-BAD",
                    "id_sensore": "S1",
                    "temperatura": 500,
                },
            )

    db.execute("SELECT count(*) AS n FROM nodi WHERE id_nodo = 'NODE-BAD'")
    assert db.fetchone()["n"] == 0


def test_a_reading_entered_through_the_api_does_not_stamp_the_node(
    session, db, make_arnia
):
    """
    Only a message from the node counts as hearing from it.

    `services.letture.record_reading` is what the API's manual insert calls.
    """
    arnia = make_arnia(id_nodo="NODE-MANUAL")

    letture.record_reading(
        session,
        {
            "id_arnia": arnia["id_arnia"],
            "id_nodo": "NODE-MANUAL",
            "temperatura": 20,
        },
    )

    assert ultimo_messaggio(db, "NODE-MANUAL")["ultimo_messaggio"] is None


# ============================================
# Where a provisioned hive goes (#36)
# ============================================


def apiario_of(db, id_nodo, id_sensore):
    db.execute(
        "SELECT id_apiario FROM arnie WHERE id_nodo = %s AND id_sensore_fisico = %s",
        (id_nodo, id_sensore),
    )
    return db.fetchone()["id_apiario"]


def test_a_hive_provisioned_for_an_owned_node_lands_in_the_owners_default(
    session, db, make_utente, make_arnia
):
    """A new sensor on a beekeeper's node shows up in their Default, unannounced."""
    utente = make_utente()
    existing = make_arnia(apiario=utente)

    ingest.record_node_reading(
        session, {"id_nodo": existing["id_nodo"], "id_sensore": "S-NEW"}
    )

    assert (
        apiario_of(db, existing["id_nodo"], "S-NEW") == utente["id_apiario_predefinito"]
    )


def test_an_unknown_node_and_its_hive_start_unassigned(session, db):
    """Nobody owns a node no admin has assigned yet; only admins see its hives."""
    ingest.record_node_reading(session, {"id_nodo": "NODE-NEW", "id_sensore": "S1"})

    db.execute("SELECT id_proprietario FROM nodi WHERE id_nodo = 'NODE-NEW'")
    assert db.fetchone()["id_proprietario"] is None
    assert apiario_of(db, "NODE-NEW", "S1") is None
