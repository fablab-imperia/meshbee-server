"""Tests for the nodi repository (meshbee_core/repository/nodi.py).

Only `upsert_seen` is covered here: the rest of this module is exercised through
the admin endpoints in tests/integration/api/. `upsert_seen` has no endpoint —
it exists for the ingest path — so without this it would be untested.
"""
from meshbee_core.repository import nodi


def test_upsert_registers_a_node_that_has_never_been_seen(db):
    """A node can start transmitting before anyone registers it through the API."""
    nodi.upsert_seen(db, "NODE-NEW", "Nodo NODE-NEW")

    row = nodi.get(db, "NODE-NEW")

    assert row["id_nodo"] == "NODE-NEW"
    assert row["nome_nodo"] == "Nodo NODE-NEW"
    assert row["attivo"] is True
    assert row["ultimo_messaggio"] is not None


def test_upsert_refreshes_the_timestamp_of_a_known_node(db):
    """The second message updates when we last heard from it."""
    nodi.upsert_seen(db, "NODE-KNOWN", "Nodo NODE-KNOWN")
    db.execute(
        "UPDATE nodi SET ultimo_messaggio = TIMESTAMP '2020-01-01 00:00:00' WHERE id_nodo = %s",
        ("NODE-KNOWN",),
    )

    nodi.upsert_seen(db, "NODE-KNOWN", "Nodo NODE-KNOWN")

    assert nodi.get(db, "NODE-KNOWN")["ultimo_messaggio"].year > 2020


def test_upsert_does_not_overwrite_a_name_given_through_the_api(db):
    """
    An operator's name for a node survives the next message.

    ON CONFLICT touches only ultimo_messaggio; were it to write nome_nodo too,
    every reading would revert the label to the generated default.
    """
    nodi.upsert_seen(db, "NODE-NAMED", "Nodo NODE-NAMED")
    db.execute(
        "UPDATE nodi SET nome_nodo = %s WHERE id_nodo = %s",
        ("Arnie del pero", "NODE-NAMED"),
    )

    nodi.upsert_seen(db, "NODE-NAMED", "Nodo NODE-NAMED")

    assert nodi.get(db, "NODE-NAMED")["nome_nodo"] == "Arnie del pero"


def test_upsert_does_not_revive_a_deactivated_node(db):
    """
    A node an admin retired stays retired even if it keeps transmitting.

    Pinned because the INSERT half of the statement says `attivo = true`; only
    the DO UPDATE branch runs for a known node, so the flag is left alone.
    """
    nodi.upsert_seen(db, "NODE-RETIRED", "Nodo NODE-RETIRED")
    nodi.deactivate(db, "NODE-RETIRED")

    nodi.upsert_seen(db, "NODE-RETIRED", "Nodo NODE-RETIRED")

    assert nodi.get(db, "NODE-RETIRED")["attivo"] is False
