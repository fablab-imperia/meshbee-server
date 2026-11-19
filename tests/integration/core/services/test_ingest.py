"""Tests for the ingest service (meshbee_core/services/ingest.py).

`ultimo_messaggio` and where a provisioned hive goes are covered here — the stored row is
the subject of tests/integration/test_ingest_parity.py, through the real MQTT
callback. These pin the two defects of the trigger this service replaced (#17):
the value came from the node's clock, so it could go backwards.
"""

import logging
from datetime import datetime, timedelta

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
                    # Not an object: the one thing about a reading ingest can't clear.
                    "dati_raw": "not an object",
                },
            )

    db.execute("SELECT count(*) AS n FROM nodi WHERE id_nodo = 'NODE-BAD'")
    assert db.fetchone()["n"] == 0


# ============================================
# Invalid measurements are cleared, not refused
# ============================================


def stored_reading(db, id_nodo):
    db.execute(
        "SELECT temperatura, umidita, peso, batteria, dati_raw FROM letture"
        " WHERE id_nodo = %s",
        (id_nodo,),
    )
    rows = db.fetchall()
    assert len(rows) == 1
    return rows[0]


def test_an_out_of_range_measurement_is_cleared_and_the_rest_kept(session, db):
    """A load cell gone negative must not cost the node its temperature."""
    ingest.record_node_reading(
        session,
        {
            "id_nodo": "NODE-SCALE",
            "id_sensore": "S1",
            "temperatura": 22.5,
            "umidita": 60,
            "peso": -12.5,
            "bat": 6.1,
        },
    )

    row = stored_reading(db, "NODE-SCALE")
    assert float(row["temperatura"]) == 22.5
    assert float(row["umidita"]) == 60
    assert row["peso"] is None
    assert row["batteria"] is None
    assert row["dati_raw"] == {"discarded": {"batteria": "6.1", "peso": "-12.5"}}
    assert ultimo_messaggio(db, "NODE-SCALE")["is_now"] is True


def test_a_measurement_that_is_not_a_number_is_cleared_too(session, db):
    ingest.record_node_reading(
        session,
        {"id_nodo": "NODE-GARBLED", "id_sensore": "S1", "umidita": "n/a", "peso": 41},
    )

    row = stored_reading(db, "NODE-GARBLED")
    assert row["umidita"] is None
    assert float(row["peso"]) == 41
    assert row["dati_raw"] == {"discarded": {"umidita": "n/a"}}


def test_the_nodes_own_dati_raw_is_kept_beside_what_was_discarded(session, db):
    ingest.record_node_reading(
        session,
        {
            "id_nodo": "NODE-RAW",
            "id_sensore": "S1",
            "temperatura": 500,
            "dati_raw": {"rssi": -67},
        },
    )

    assert stored_reading(db, "NODE-RAW")["dati_raw"] == {
        "rssi": -67,
        "discarded": {"temperatura": "500"},
    }


def test_a_valid_reading_gets_no_discarded_entry(session, db):
    ingest.record_node_reading(
        session, {"id_nodo": "NODE-FINE", "id_sensore": "S1", "temperatura": 20}
    )

    assert stored_reading(db, "NODE-FINE")["dati_raw"] is None


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


# ============================================
# Duplicates within the window are dropped (#4)
# ============================================

WINDOW = timedelta(minutes=5)


def readings_of(db, id_nodo):
    db.execute("SELECT count(*) AS n FROM letture WHERE id_nodo = %s", (id_nodo,))
    return db.fetchone()["n"]


def test_the_four_retransmissions_store_one_reading(session, db, caplog):
    """The sender repeats every reading 4 times; without a clock all look new."""
    payload = {"id_nodo": "NODE-REPEAT", "id_sensore": "S1", "temperatura": 20}

    with caplog.at_level(logging.INFO):
        results = [
            ingest.record_node_reading(session, payload, dedup_window=WINDOW)
            for _ in range(4)
        ]

    assert results[0] is not None
    assert results[1:] == [None, None, None]
    assert readings_of(db, "NODE-REPEAT") == 1
    assert caplog.text.count("Lettura duplicata ignorata") == 3


def test_a_dropped_copy_is_logged_with_what_it_carried_and_what_it_matched(
    session, db, caplog
):
    """The line alone must say which reading was dropped and which one stayed."""
    timestamp = datetime(2026, 6, 1, 12, 0, 0)
    payload = {
        "id_nodo": "NODE-LOGGED",
        "id_sensore": "S1",
        "timestamp": timestamp,
        "temperatura": 34.5,
        "umidita": 65,
        "peso": 42.35,
        "bat": 4.01,
    }
    kept = ingest.record_node_reading(session, payload, dedup_window=WINDOW)

    with caplog.at_level(logging.INFO):
        ingest.record_node_reading(session, payload, dedup_window=WINDOW)

    (line,) = [r.getMessage() for r in caplog.records if "duplicata" in r.getMessage()]
    assert f"arnia {kept['id_arnia']}" in line
    assert "nodo: NODE-LOGGED, sensore: S1" in line
    assert "timestamp: 2026-06-01 12:00:00" in line
    assert "T: 34.5°C" in line
    assert "B: 4.01V" in line
    assert f"lettura {kept['id_lettura']} delle 2026-06-01 12:00:00" in line


def test_a_duplicate_still_counts_as_hearing_from_the_node(session, db):
    payload = {"id_nodo": "NODE-HEARD", "id_sensore": "S1"}
    ingest.record_node_reading(session, payload, dedup_window=WINDOW)
    db.execute("UPDATE nodi SET ultimo_messaggio = NULL WHERE id_nodo = 'NODE-HEARD'")

    assert ingest.record_node_reading(session, payload, dedup_window=WINDOW) is None
    assert ultimo_messaggio(db, "NODE-HEARD")["is_now"] is True


@pytest.mark.parametrize(
    ("gap", "stored"), [(timedelta(seconds=1), 1), (timedelta(minutes=6), 2)]
)
def test_node_timestamps_are_compared_against_the_window(session, db, gap, stored):
    first = datetime(2026, 6, 1, 12, 0, 0)
    for timestamp in (first, first + gap):
        ingest.record_node_reading(
            session,
            {"id_nodo": "NODE-CLOCK", "id_sensore": "S1", "timestamp": timestamp},
            dedup_window=WINDOW,
        )

    assert readings_of(db, "NODE-CLOCK") == stored


def test_each_sensor_of_a_node_keeps_its_own_reading(session, db):
    """Dedup is per arnia: two hives on one node are not duplicates of each other."""
    for id_sensore in ("S1", "S2"):
        ingest.record_node_reading(
            session,
            {"id_nodo": "NODE-TWIN", "id_sensore": id_sensore},
            dedup_window=WINDOW,
        )

    assert readings_of(db, "NODE-TWIN") == 2


def test_without_a_window_every_message_is_stored(session, db):
    payload = {"id_nodo": "NODE-ALL", "id_sensore": "S1"}
    ingest.record_node_reading(session, payload)
    ingest.record_node_reading(session, payload)

    assert readings_of(db, "NODE-ALL") == 2


def test_the_api_path_never_deduplicates(session, db, make_arnia):
    """A person entering a reading means it, however close to the last one."""
    arnia = make_arnia(id_nodo="NODE-HAND")
    reading = {"id_arnia": arnia["id_arnia"], "id_nodo": "NODE-HAND", "temperatura": 20}
    ingest.record_node_reading(
        session,
        {"id_nodo": "NODE-HAND", "id_sensore": arnia["id_sensore_fisico"]},
        dedup_window=WINDOW,
    )

    letture.record_reading(session, reading)
    letture.record_reading(session, reading)

    assert readings_of(db, "NODE-HAND") == 3
