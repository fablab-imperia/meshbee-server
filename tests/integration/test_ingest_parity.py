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
def deliver(monkeypatch, db):
    """
    Deliver a message to the real MQTT callback, inside the test transaction.

    Patches `get_db_cursor` on the handler module — the same seam `use_db` uses
    for `main` and `auth`, and for the same reason: the module holds its own
    reference to the name it imported.

    Unlike `use_db` this wraps each message in a SAVEPOINT, because in
    production every message gets its own transaction: `get_db_cursor` commits
    on a clean exit and rolls back on an exception. A plain shared cursor would
    keep the writes of a message that was supposed to be discarded, which is
    exactly the behaviour these tests are here to check.
    """
    from contextlib import contextmanager

    @contextmanager
    def _cursor():
        db.execute("SAVEPOINT messaggio")
        try:
            yield db
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT messaggio")
            raise
        db.execute("RELEASE SAVEPOINT messaggio")

    monkeypatch.setattr(mqtt_entry, "get_db_cursor", _cursor)

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
        json={"id_arnia": arnia["id_arnia"], "id_nodo": arnia["id_nodo"], **MEASUREMENTS},
    )
    assert response.status_code == 200

    from_mqtt, from_api = stored(db, arnia["id_arnia"])

    compared = set(from_mqtt) - NOT_COMPARED
    assert compared, "no columns were compared"
    for column in compared:
        # `timestamp` defaults to CURRENT_TIMESTAMP on both paths; within one
        # transaction that is the same instant, so it compares equal too.
        assert from_mqtt[column] == from_api[column], f"colonna divergente: {column}"


def test_both_paths_write_the_measurements_they_were_given(db, deliver, as_user,
                                                           make_utente, make_arnia):
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


def test_both_paths_refuse_the_same_out_of_range_reading(db, deliver, as_user,
                                                         make_utente, make_arnia):
    """
    A value the API rejects is now also rejected on ingest.

    Before the extraction the MQTT path had no validation: the reading reached
    Postgres, tripped the CHECK constraint, and was rolled back and lost.
    """
    arnia = make_arnia(id_nodo="NODE-PARITY")
    admin = make_utente(ruolo="admin")

    deliver(
        "beehive/NODE-PARITY/data",
        {"id_sensore": arnia["id_sensore_fisico"], "temperatura": 500},
    )

    response = as_user(admin).post(
        "/api/admin/letture",
        json={"id_arnia": arnia["id_arnia"], "id_nodo": arnia["id_nodo"], "temperatura": 500},
    )

    assert response.status_code == 422
    assert stored(db, arnia["id_arnia"]) == []


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
    deliver("beehive/NODE-NEW/data", {"id_sensore": "SENSOR-NEW", **on_the_wire(MEASUREMENTS)})

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


def test_resolving_an_unregistered_node_without_a_sensor_raises(db):
    """The service says why, rather than returning None for the caller to interpret."""
    from meshbee_core.errors import NotFound

    with pytest.raises(NotFound):
        ingest.register_node_and_resolve_arnia(db, "NODE-NOWHERE", None)
