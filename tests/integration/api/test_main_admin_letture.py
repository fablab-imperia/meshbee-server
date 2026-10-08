"""Deleting readings: one by id, or a selection in bulk (#21)."""

import pytest


@pytest.fixture
def admin(as_user, make_utente):
    """A client authenticated as an admin."""
    return as_user(make_utente(ruolo="admin"))


@pytest.fixture
def ids_left(db):
    """The ids of the readings still in the table for a hive."""

    def _ids(arnia):
        db.execute(
            "SELECT id_lettura FROM letture WHERE id_arnia = %s ORDER BY id_lettura",
            (arnia["id_arnia"],),
        )
        return [row["id_lettura"] for row in db.fetchall()]

    return _ids


def test_deleting_one_reading_leaves_the_others(
    admin, make_arnia, make_lettura, ids_left
):
    arnia = make_arnia()
    gone, kept = make_lettura(arnia), make_lettura(arnia)

    response = admin.delete(f"/api/admin/letture/{gone['id_lettura']}")

    assert response.status_code == 200
    assert ids_left(arnia) == [kept["id_lettura"]]


def test_deleting_an_unknown_reading_is_not_found(admin):
    assert admin.delete("/api/admin/letture/999999").status_code == 404


def test_a_bulk_delete_removes_exactly_the_listed_readings(
    admin, make_arnia, make_lettura, ids_left
):
    arnia, altra = make_arnia(), make_arnia()
    a, b, c = (make_lettura(arnia) for _ in range(3))
    other = make_lettura(altra)

    response = admin.post(
        "/api/admin/letture/elimina",
        json={"id_letture": [a["id_lettura"], c["id_lettura"]]},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "2 letture eliminate"
    assert ids_left(arnia) == [b["id_lettura"]]
    assert ids_left(altra) == [other["id_lettura"]]


def test_a_bulk_delete_skips_unknown_and_repeated_ids(
    admin, make_arnia, make_lettura, ids_left
):
    """A reading already gone is what the caller wanted; it is not counted."""
    arnia = make_arnia()
    lettura = make_lettura(arnia)

    response = admin.post(
        "/api/admin/letture/elimina",
        json={"id_letture": [lettura["id_lettura"], lettura["id_lettura"], 999999]},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "1 letture eliminate"
    assert ids_left(arnia) == []


def test_a_bulk_delete_needs_at_least_one_id(admin):
    assert (
        admin.post("/api/admin/letture/elimina", json={"id_letture": []}).status_code
        == 422
    )


def test_deleting_readings_leaves_the_node_last_message_alone(
    admin, db, make_arnia, make_lettura
):
    """`nodi.ultimo_messaggio` is the receipt time of the last MQTT message,
    owned by ingest; deleting readings does not rewrite it."""
    arnia = make_arnia()
    db.execute(
        "UPDATE nodi SET ultimo_messaggio = '2026-01-01T10:00:00' WHERE id_nodo = %s",
        (arnia["id_nodo"],),
    )
    lettura = make_lettura(arnia)

    admin.delete(f"/api/admin/letture/{lettura['id_lettura']}")

    db.execute(
        "SELECT ultimo_messaggio FROM nodi WHERE id_nodo = %s", (arnia["id_nodo"],)
    )
    assert db.fetchone()["ultimo_messaggio"].isoformat() == "2026-01-01T10:00:00"
