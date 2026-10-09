"""The two write paths must agree.

This is the regression the whole service-layer extraction exists to prevent:
readings reach `letture` through the MQTT handler and through the API's manual
insert endpoint, and before the refactor each carried its own copy of the
INSERT. A column added to one and not the other would have gone unnoticed until
the data was queried.

Everything here goes through the real entry points — `handler.on_message` with a
real MQTT message object, and an HTTP request through the TestClient — so it
fails if either stops routing through the shared service.
"""

import json
from types import SimpleNamespace

import pytest

from meshbee_core.services import ingest
from mqtt_handler import handler as mqtt_entry

# Columns that legitimately differ between two separate rows.
NOT_COMPARED = {"id_lettura"}

MEASUREMENTS = {"temperatura": 34.5, "umidita": 65.0, "peso": 42.35, "batteria": 4.01}


def on_the_wire(measurements):
    """The same measurements as a node sends them: the firmware calls it `bat`."""
    wire = dict(measurements)
    wire["bat"] = wire.pop("batteria")
    return wire


def mqtt_message(topic, payload):
    """The shape paho hands to `on_message`: `.topic` and raw `.payload` bytes."""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode("utf-8"))


@pytest.fixture
def deliver(use_db):
    """
    Deliver a message to the real MQTT callback, inside the test transaction.

    `use_db` patches `get_session` on the handler module — the module holds its
    own reference to the name it imported. Each message then gets its own
    session on a SAVEPOINT, as in production every message gets its own
    transaction: a message that fails is rolled back without touching the
    others, which is exactly the behaviour these tests are here to check.
    """
    use_db(mqtt_entry)

    def _deliver(topic, payload):
        mqtt_entry.BeehiveMQTTHandler.on_message(
            None, None, None, mqtt_message(topic, payload)
        )

    return _deliver


def stored(db, id_arnia):
    """Every column of the readings for an arnia, oldest first."""
    db.execute(
        "SELECT * FROM letture WHERE id_arnia = %s ORDER BY id_lettura", (id_arnia,)
    )
    return [dict(row) for row in db.fetchall()]


def test_a_reading_via_mqtt_and_via_the_api_produce_equivalent_rows(
    db, deliver, as_user, make_utente, make_arnia
):
    """
    The same measurements, delivered both ways, differ only by primary key.

    Compares *every* column rather than a chosen few, so a column one path
    starts writing and the other does not fails here.
    """
    arnia = make_arnia(id_nodo="NODE-PARITY")
    admin = make_utente(ruolo="admin")

    deliver(
        "beehive/NODE-PARITY/data",
        {"id_sensore": arnia["id_sensore_fisico"], **on_the_wire(MEASUREMENTS)},
    )

    response = as_user(admin).post(
        "/api/admin/letture",
        json={
            "id_arnia": arnia["id_arnia"],
            "id_nodo": arnia["id_nodo"],
            **MEASUREMENTS,
        },
    )
    assert response.status_code == 200

    from_mqtt, from_api = stored(db, arnia["id_arnia"])

    compared = set(from_mqtt) - NOT_COMPARED
    assert compared, "no columns were compared"
    for column in compared:
        # `timestamp` defaults to CURRENT_TIMESTAMP on both paths; within one
        # transaction that is the same instant, so it compares equal too.
        assert from_mqtt[column] == from_api[column], f"colonna divergente: {column}"


def test_both_paths_write_the_measurements_they_were_given(
    db, deliver, as_user, make_utente, make_arnia
):
    """Equivalence would be vacuous if both paths stored nothing."""
    arnia = make_arnia(id_nodo="NODE-PARITY")

    deliver(
        "beehive/NODE-PARITY/data",
        {"id_sensore": arnia["id_sensore_fisico"], **on_the_wire(MEASUREMENTS)},
    )

    row = stored(db, arnia["id_arnia"])[0]

    assert float(row["temperatura"]) == MEASUREMENTS["temperatura"]
    assert float(row["umidita"]) == MEASUREMENTS["umidita"]
    assert float(row["peso"]) == MEASUREMENTS["peso"]
    assert float(row["batteria"]) == MEASUREMENTS["batteria"]
    assert row["id_nodo"] == arnia["id_nodo"]


def test_an_out_of_range_value_is_refused_by_the_api_and_cleared_by_ingest(
    db, deliver, as_user, make_utente, make_arnia
):
    """
    The same limits, applied differently on purpose.

    The API answers 422: whoever typed the value can correct it. A node can't,
    so the MQTT path stores the reading with that one measurement cleared,
    rather than losing the others with it.
    """
    arnia = make_arnia(id_nodo="NODE-PARITY")
    admin = make_utente(ruolo="admin")

    deliver(
        "beehive/NODE-PARITY/data",
        {"id_sensore": arnia["id_sensore_fisico"], "temperatura": 500, "umidita": 60},
    )

    response = as_user(admin).post(
        "/api/admin/letture",
        json={
            "id_arnia": arnia["id_arnia"],
            "id_nodo": arnia["id_nodo"],
            "temperatura": 500,
            "umidita": 60,
        },
    )

    assert response.status_code == 422
    (row,) = stored(db, arnia["id_arnia"])
    assert row["temperatura"] is None
    assert float(row["umidita"]) == 60


def test_the_api_refuses_a_reading_for_an_unknown_arnia(as_user, make_utente):
    """
    Half of the one place the paths deliberately differ.

    An admin naming a nonexistent arnia has made a mistake, so the foreign-key
    violation becomes a 404 rather than provisioning something.

    Kept apart from the ingest half because the violation aborts the shared test
    transaction, so nothing may query afterwards — the same constraint
    test_main_admin_errors.py works under.
    """
    admin = make_utente(ruolo="admin")

    response = as_user(admin).post(
        "/api/admin/letture",
        json={"id_arnia": 999999, "id_nodo": "NODE-UNKNOWN", **MEASUREMENTS},
    )

    assert response.status_code == 404


def test_ingest_provisions_the_arnia_the_api_would_have_refused(db, deliver):
    """
    The other half: a node may transmit before anyone registers it.

    Same reading the API refuses above, arriving over MQTT, is stored — against
    a nodo and arnia the handler creates on the spot.
    """
    deliver(
        "beehive/NODE-NEW/data",
        {"id_sensore": "SENSOR-NEW", **on_the_wire(MEASUREMENTS)},
    )

    db.execute("SELECT id_arnia FROM arnie WHERE id_nodo = %s", ("NODE-NEW",))
    created = db.fetchone()

    assert created is not None, "l'ingest deve creare l'arnia mancante"
    assert len(stored(db, created["id_arnia"])) == 1


def test_ingest_does_not_persist_the_node_when_the_arnia_is_unresolvable(db, deliver):
    """
    A rejected message must leave nothing behind, node registration included.

    `register_node_and_resolve_arnia` upserts `nodi` before it looks for the
    arnia, and the caller's cursor commits on a clean exit — so it has to raise
    rather than return, or every unusable message would leave a ghost node.
    """
    deliver("beehive/NODE-GHOST/data", {"temperatura": 20})

    db.execute("SELECT id_nodo FROM nodi WHERE id_nodo = %s", ("NODE-GHOST",))
    assert db.fetchone() is None


def test_resolving_an_unregistered_node_without_a_sensor_raises(session, db):
    """The service says why, rather than returning None for the caller to interpret."""
    from meshbee_core.errors import NotFound

    with pytest.raises(NotFound):
        ingest.register_node_and_resolve_arnia(session, "NODE-NOWHERE", None)
