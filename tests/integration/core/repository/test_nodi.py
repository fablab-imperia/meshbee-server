"""Tests for the nodi repository (meshbee_core/repository/nodi.py).

Only `register_if_absent` is covered here: the rest of this module is exercised
through the admin endpoints in tests/integration/api/. This one has no endpoint —
it exists for the ingest path — so without this it would be untested.
"""

from meshbee_core.repository import letture, nodi


def test_a_node_that_has_never_been_seen_is_registered(session, db):
    """A node can start transmitting before anyone registers it through the API."""
    nodi.register_if_absent(session, "NODE-NEW", "Nodo NODE-NEW")

    row = nodi.get(session, "NODE-NEW")

    assert row["id_nodo"] == "NODE-NEW"
    assert row["nome_nodo"] == "Nodo NODE-NEW"
    assert row["attivo"] is True


def test_registering_a_known_node_changes_nothing(session, db):
    """
    The second message must leave the existing row exactly as it stands.

    ON CONFLICT DO NOTHING rather than DO UPDATE: everything worth updating on
    a repeat sighting is either stamped separately (`ultimo_messaggio`, by
    `touch_ultimo_messaggio`) or an operator's to set (`nome_nodo`).
    """
    nodi.register_if_absent(session, "NODE-KNOWN", "Nodo NODE-KNOWN")
    before = nodi.get(session, "NODE-KNOWN")

    nodi.register_if_absent(session, "NODE-KNOWN", "Nodo NODE-KNOWN")

    assert nodi.get(session, "NODE-KNOWN") == before


def test_registering_does_not_overwrite_a_name_given_through_the_api(session, db):
    """
    An operator's name for a node survives the next message.

    Were the conflict branch to write nome_nodo, every reading would revert the
    label to the generated default.
    """
    nodi.register_if_absent(session, "NODE-NAMED", "Nodo NODE-NAMED")
    db.execute(
        "UPDATE nodi SET nome_nodo = %s WHERE id_nodo = %s",
        ("Arnie del pero", "NODE-NAMED"),
    )

    nodi.register_if_absent(session, "NODE-NAMED", "Nodo NODE-NAMED")

    assert nodi.get(session, "NODE-NAMED")["nome_nodo"] == "Arnie del pero"


def test_registering_does_not_revive_a_deactivated_node(session, db):
    """
    A node an admin retired stays retired even if it keeps transmitting.

    Pinned because the INSERT half of the statement says `attivo = true`; only
    the conflict branch runs for a known node, and it does nothing.
    """
    nodi.register_if_absent(session, "NODE-RETIRED", "Nodo NODE-RETIRED")
    nodi.deactivate(session, "NODE-RETIRED")

    nodi.register_if_absent(session, "NODE-RETIRED", "Nodo NODE-RETIRED")

    assert nodi.get(session, "NODE-RETIRED")["attivo"] is False


# ============================================
# Who owns `ultimo_messaggio`
# ============================================


def test_registering_alone_does_not_stamp_a_sighting(session, db):
    """
    Registering a node is not the same as having heard from it.

    The column stays empty until `touch_ultimo_messaggio` runs, which the
    ingest service does once a reading is stored.
    """
    nodi.register_if_absent(session, "NODE-QUIET", "Nodo NODE-QUIET")

    assert nodi.get(session, "NODE-QUIET")["ultimo_messaggio"] is None


def test_storing_a_reading_does_not_stamp_the_node(session, db, make_arnia):
    """
    The database no longer decides this: there is no trigger on `letture`.

    A reading inserted through the repository — as the API's manual insert and
    the seed do — leaves the node alone. Pinned so that a trigger reappearing
    fails here, as well as in tests/integration/test_migrations.py.
    """
    arnia = make_arnia(id_nodo="NODE-TALKING")

    letture.insert(
        session,
        id_arnia=arnia["id_arnia"],
        id_nodo="NODE-TALKING",
        timestamp=None,
        temperatura=20,
        umidita=None,
        peso=None,
        dati_raw=None,
    )

    assert nodi.get(session, "NODE-TALKING")["ultimo_messaggio"] is None


def test_touching_stamps_the_database_clock(session, db):
    nodi.register_if_absent(session, "NODE-HEARD", "Nodo NODE-HEARD")

    nodi.touch_ultimo_messaggio(session, "NODE-HEARD")

    db.execute(
        "SELECT ultimo_messaggio = CURRENT_TIMESTAMP AS now FROM nodi WHERE id_nodo = %s",
        ("NODE-HEARD",),
    )
    # One transaction, so CURRENT_TIMESTAMP is the same instant the UPDATE saw.
    assert db.fetchone()["now"] is True
