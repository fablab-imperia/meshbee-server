"""Tests for the arnie repository (meshbee_core/repository/arnie.py).

Covers the two lookups the ingest path needs — which have no HTTP endpoint — and
the UNSET sentinel on `update`, which is what stops a user with write permission
retiring a hive.
"""
from meshbee_core.repository import arnie


def test_an_arnia_is_found_by_node_and_sensor(db, make_arnia):
    """How a reading is matched to the hive it came from."""
    arnia = make_arnia(id_nodo="NODE-LOOKUP")

    found = arnie.find_id_by_nodo_sensore(db, "NODE-LOOKUP", arnia["id_sensore_fisico"])

    assert found["id_arnia"] == arnia["id_arnia"]


def test_an_unknown_sensor_is_not_found(db, make_arnia):
    """A sensor id we have never seen is what triggers provisioning upstream."""
    make_arnia(id_nodo="NODE-LOOKUP")

    assert arnie.find_id_by_nodo_sensore(db, "NODE-LOOKUP", "SENSOR-ABSENT") is None


def test_the_sensor_lookup_is_scoped_to_its_node(db, make_arnia):
    """
    The same sensor id on another node is a different hive.

    `id_sensore_fisico` is only unique per node — UNIQUE(id_nodo,
    id_sensore_fisico) — so the node must be part of the lookup.
    """
    first = make_arnia(id_nodo="NODE-A")
    db.execute(
        "INSERT INTO nodi (id_nodo, nome_nodo) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        ("NODE-B", "Nodo B"),
    )
    db.execute(
        "INSERT INTO arnie (id_nodo, id_sensore_fisico) VALUES (%s, %s) RETURNING id_arnia",
        ("NODE-B", first["id_sensore_fisico"]),
    )
    other = db.fetchone()["id_arnia"]

    found = arnie.find_id_by_nodo_sensore(db, "NODE-B", first["id_sensore_fisico"])

    assert found["id_arnia"] == other != first["id_arnia"]


def test_the_first_arnia_of_a_node_is_the_lowest_id(db, make_arnia):
    """The fallback for readings that carry no sensor id must be deterministic."""
    first = make_arnia(id_nodo="NODE-MULTI")
    make_arnia(id_nodo="NODE-MULTI")

    assert arnie.find_first_id_by_nodo(db, "NODE-MULTI")["id_arnia"] == first["id_arnia"]


def test_a_node_with_no_arnie_resolves_to_nothing(db):
    """Nothing to fall back to, which is what makes the reading unattributable."""
    db.execute(
        "INSERT INTO nodi (id_nodo, nome_nodo) VALUES (%s, %s)", ("NODE-BARE", "Nodo")
    )

    assert arnie.find_first_id_by_nodo(db, "NODE-BARE") is None


# ============================================
# The attiva sentinel
# ============================================


def test_attiva_is_untouched_when_not_passed(db, make_arnia):
    """
    Omitting `attiva` leaves the column out of the statement entirely.

    This is what the user-facing update endpoint relies on: write permission on
    a hive must not let someone retire it.
    """
    arnia = make_arnia()
    arnie.update(db, arnia["id_arnia"], nome_arnia="Rinominata")

    updated = arnie.get_stato(db, arnia["id_arnia"])

    assert updated["nome_arnia"] == "Rinominata"
    assert updated["attiva"] is True


def test_attiva_is_applied_when_passed(db, make_arnia):
    """The admin endpoint does pass it, and then it takes effect."""
    arnia = make_arnia()

    arnie.update(db, arnia["id_arnia"], attiva=False)

    assert arnie.get_stato(db, arnia["id_arnia"])["attiva"] is False


def test_passing_attiva_as_none_keeps_the_stored_value(db, make_arnia):
    """
    None is not the same as omitted: COALESCE keeps what is stored.

    ArniaUpdate leaves `attiva` unset most of the time, so the admin endpoint
    passes None on nearly every request and must not flip anything.
    """
    arnia = make_arnia()

    arnie.update(db, arnia["id_arnia"], nome_arnia="X", attiva=None)

    assert arnie.get_stato(db, arnia["id_arnia"])["attiva"] is True


def test_unmentioned_fields_keep_their_value(db, make_arnia):
    """
    A partial update is genuinely partial.

    Asserted on the RETURNING row rather than v_arnie_stato, which projects only
    the columns the app charts and does not carry `descrizione`.
    """
    arnia = make_arnia()
    arnie.update(db, arnia["id_arnia"], descrizione="Prima descrizione")

    updated = arnie.update(db, arnia["id_arnia"], nome_arnia="Nuovo nome")

    assert updated["nome_arnia"] == "Nuovo nome"
    assert updated["descrizione"] == "Prima descrizione"


def test_updating_a_missing_arnia_returns_nothing(db):
    """The caller turns this into a 404; the repository just reports no row."""
    assert arnie.update(db, 999999, nome_arnia="X") is None
