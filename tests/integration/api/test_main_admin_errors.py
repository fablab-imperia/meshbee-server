"""Status codes the admin write endpoints return on constraint violations.

A database constraint failing is a client mistake, not a server fault: it must
map to 409 (already exists) or 404 (referenced row missing), never to a bare 500
that tells the caller nothing.

Note each test triggers at most one violation: the first one aborts the
transaction the `db` fixture holds, so nothing after it can query.
"""

import pytest


@pytest.fixture
def admin_client(as_user, make_utente):
    """A client authenticated as an admin."""
    return as_user(make_utente(ruolo="admin"))


# ============================================
# Conflicts → 409
# ============================================


def test_creating_a_user_with_a_taken_email_is_a_conflict(admin_client, make_utente):
    """The pre-check reports the clash rather than letting the UNIQUE index fire."""
    existing = make_utente()

    response = admin_client.post(
        "/api/admin/utenti",
        json={
            "email": existing["email"],
            "nome": "N",
            "cognome": "C",
            "password": "secret123",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email già registrata"


def test_updating_a_user_to_a_taken_email_is_a_conflict(admin_client, make_utente):
    """Update has no pre-check, so the UNIQUE violation is mapped instead of escaping as a 500."""
    target, other = make_utente(), make_utente()

    response = admin_client.put(
        f"/api/admin/utenti/{target['id_utente']}", json={"email": other["email"]}
    )

    assert response.status_code == 409


def test_registering_an_existing_nodo_is_a_conflict(admin_client, make_arnia):
    """Re-registering a node id reports the clash."""
    arnia = make_arnia()

    response = admin_client.post("/api/admin/nodi", json={"id_nodo": arnia["id_nodo"]})

    assert response.status_code == 409


def test_reusing_a_sensor_on_the_same_nodo_is_a_conflict(admin_client, make_arnia):
    """UNIQUE(id_nodo, id_sensore_fisico) — the pair identifies a physical hive."""
    arnia = make_arnia()

    response = admin_client.post(
        "/api/admin/arnie",
        json={
            "id_nodo": arnia["id_nodo"],
            "id_sensore_fisico": arnia["id_sensore_fisico"],
        },
    )

    assert response.status_code == 409


def test_the_same_sensor_id_is_allowed_on_a_different_nodo(
    admin_client, make_arnia, db
):
    """The constraint is on the pair, so the conflict really is scoped to one node."""
    arnia = make_arnia()
    db.execute("INSERT INTO nodi (id_nodo, nome_nodo) VALUES ('NODE-ALTRO', 'Altro')")

    response = admin_client.post(
        "/api/admin/arnie",
        json={"id_nodo": "NODE-ALTRO", "id_sensore_fisico": arnia["id_sensore_fisico"]},
    )

    assert response.status_code == 200


# ============================================
# Missing references → 404
# ============================================


def test_creating_an_arnia_on_an_unknown_nodo_is_not_found(admin_client):
    """The FK to nodi fails: the node is missing, which is a 404, not a server error."""
    response = admin_client.post(
        "/api/admin/arnie", json={"id_nodo": "NON-ESISTE", "id_sensore_fisico": "S9"}
    )

    assert response.status_code == 404
    assert "NON-ESISTE" in response.json()["detail"]


def test_assigning_a_node_to_an_unknown_user_is_not_found(admin_client, make_arnia):
    arnia = make_arnia()

    response = admin_client.put(
        f"/api/admin/nodi/{arnia['id_nodo']}/proprietario", json={"id_utente": 999999}
    )

    assert response.status_code == 404


def test_assigning_an_unknown_node_is_not_found(admin_client, make_utente):
    response = admin_client.put(
        "/api/admin/nodi/NON-ESISTE/proprietario",
        json={"id_utente": make_utente()["id_utente"]},
    )

    assert response.status_code == 404


def test_inserting_a_reading_for_an_unknown_arnia_is_not_found(admin_client):
    """Manual backfill against a missing arnia is a 404."""
    response = admin_client.post(
        "/api/admin/letture", json={"id_arnia": 999999, "id_nodo": "NODE-TEST"}
    )

    assert response.status_code == 404


# ============================================
# The happy paths still work
# ============================================


def test_a_valid_node_assignment_still_succeeds(admin_client, make_utente, make_arnia):
    """The new except clauses do not shadow the normal path."""
    utente, arnia = make_utente(), make_arnia()

    response = admin_client.put(
        f"/api/admin/nodi/{arnia['id_nodo']}/proprietario",
        json={"id_utente": utente["id_utente"]},
    )

    assert response.status_code == 200


def test_a_valid_reading_still_succeeds(admin_client, make_arnia):
    """Inserting against an existing arnia is unaffected."""
    arnia = make_arnia()

    response = admin_client.post(
        "/api/admin/letture",
        json={
            "id_arnia": arnia["id_arnia"],
            "id_nodo": arnia["id_nodo"],
            "temperatura": "34.5",
        },
    )

    assert response.status_code == 200
    assert float(response.json()["temperatura"]) == 34.5


def test_a_valid_user_update_still_succeeds(admin_client, make_utente):
    """Changing an email to a free address works."""
    utente = make_utente()

    response = admin_client.put(
        f"/api/admin/utenti/{utente['id_utente']}", json={"email": "nuova@example.org"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "nuova@example.org"
