"""Tests for the nodi repository (meshbee_core/repository/nodi.py).

Only `register_if_absent` is covered here: the rest of this module is exercised
through the admin endpoints in tests/integration/api/. This one has no endpoint —
it exists for the ingest path — so without this it would be untested.
"""
from meshbee_core.repository import letture, nodi


def test_a_node_that_has_never_been_seen_is_registered(db):
    """A node can start transmitting before anyone registers it through the API."""
    nodi.register_if_absent(db, "NODE-NEW", "Nodo NODE-NEW")

    row = nodi.get(db, "NODE-NEW")

    assert row["id_nodo"] == "NODE-NEW"
    assert row["nome_nodo"] == "Nodo NODE-NEW"
    assert row["attivo"] is True


def test_registering_a_known_node_changes_nothing(db):
    """
    The second message must leave the existing row exactly as it stands.

    ON CONFLICT DO NOTHING rather than DO UPDATE: everything worth updating on
    a repeat sighting is either owned elsewhere (`ultimo_messaggio`, by the
    trigger) or an operator's to set (`nome_nodo`).
    """
    nodi.register_if_absent(db, "NODE-KNOWN", "Nodo NODE-KNOWN")
    before = nodi.get(db, "NODE-KNOWN")

    nodi.register_if_absent(db, "NODE-KNOWN", "Nodo NODE-KNOWN")

    assert nodi.get(db, "NODE-KNOWN") == before


def test_registering_does_not_overwrite_a_name_given_through_the_api(db):
    """
    An operator's name for a node survives the next message.

    Were the conflict branch to write nome_nodo, every reading would revert the
    label to the generated default.
    """
    nodi.register_if_absent(db, "NODE-NAMED", "Nodo NODE-NAMED")
    db.execute(
        "UPDATE nodi SET nome_nodo = %s WHERE id_nodo = %s",
        ("Arnie del pero", "NODE-NAMED"),
    )

    nodi.register_if_absent(db, "NODE-NAMED", "Nodo NODE-NAMED")

    assert nodi.get(db, "NODE-NAMED")["nome_nodo"] == "Arnie del pero"


def test_registering_does_not_revive_a_deactivated_node(db):
    """
    A node an admin retired stays retired even if it keeps transmitting.

    Pinned because the INSERT half of the statement says `attivo = true`; only
    the conflict branch runs for a known node, and it does nothing.
    """
    nodi.register_if_absent(db, "NODE-RETIRED", "Nodo NODE-RETIRED")
    nodi.deactivate(db, "NODE-RETIRED")

    nodi.register_if_absent(db, "NODE-RETIRED", "Nodo NODE-RETIRED")

    assert nodi.get(db, "NODE-RETIRED")["attivo"] is False


# ============================================
# Who owns `ultimo_messaggio`
# ============================================


def test_registering_alone_does_not_stamp_a_sighting(db):
    """
    Registering a node is not the same as having heard from it.

    The column stays empty until a reading actually lands, which is what makes
    the trigger the single writer.
    """
    nodi.register_if_absent(db, "NODE-QUIET", "Nodo NODE-QUIET")

    assert nodi.get(db, "NODE-QUIET")["ultimo_messaggio"] is None


def test_a_reading_is_what_stamps_the_node(db, make_arnia):
    """
    `trigger_aggiorna_nodo` on `letture` maintains `nodi.ultimo_messaggio`.

    The ingest path relies on this: it deliberately writes nothing to the
    column, because anything it wrote would be overwritten here anyway. If the
    trigger is ever dropped, this fails rather than the column silently going
    stale.

    Asserted as "is stamped" rather than a specific value on purpose — see
    CLAUDE.md on the trigger recording the sensor's clock rather than ours.
    """
    arnia = make_arnia(id_nodo="NODE-TALKING")
    assert nodi.get(db, "NODE-TALKING")["ultimo_messaggio"] is None

    letture.insert(
        db, id_arnia=arnia["id_arnia"], id_nodo="NODE-TALKING", timestamp=None,
        temperatura=20, umidita=None, peso=None, dati_raw=None,
    )

    assert nodi.get(db, "NODE-TALKING")["ultimo_messaggio"] is not None
