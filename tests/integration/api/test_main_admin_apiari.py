"""The /api/admin/apiari endpoints, and assigning hives through the admin hive routes."""

import pytest


@pytest.fixture
def admin(as_user, make_utente):
    """A client authenticated as an admin."""
    return as_user(make_utente(ruolo="admin"))


def test_an_apiario_is_created_and_read_back(admin, make_utente):
    owner = make_utente()

    created = admin.post(
        "/api/admin/apiari",
        json={
            "nome_apiario": "Collina",
            "latitudine": "45.464200",
            "longitudine": "9.190000",
            "id_utente_proprietario": owner["id_utente"],
        },
    )

    assert created.status_code == 200
    body = admin.get(f"/api/admin/apiari/{created.json()['id_apiario']}").json()
    assert body["nome_apiario"] == "Collina"
    assert body["id_utente_proprietario"] == owner["id_utente"]
    assert body["attivo"] is True


def test_an_unknown_owner_is_not_found(admin):
    response = admin.post(
        "/api/admin/apiari",
        json={"nome_apiario": "Collina", "id_utente_proprietario": 999999},
    )

    assert response.status_code == 404


def test_coordinates_out_of_range_are_refused(admin):
    """The same bounds as a hive's, from limits.py."""
    response = admin.post(
        "/api/admin/apiari", json={"nome_apiario": "Collina", "latitudine": "91"}
    )

    assert response.status_code == 422


def test_the_admin_list_includes_retired_apiari(admin, make_apiario):
    active, retired = make_apiario(), make_apiario(attivo=False)

    body = admin.get("/api/admin/apiari").json()

    assert [a["id_apiario"] for a in body] == [
        active["id_apiario"],
        retired["id_apiario"],
    ]


def test_an_unknown_apiario_is_not_found(admin):
    assert admin.get("/api/admin/apiari/999999").status_code == 404
    assert admin.put("/api/admin/apiari/999999", json={}).status_code == 404
    assert admin.delete("/api/admin/apiari/999999").status_code == 404


def test_an_empty_apiario_is_retired(admin, make_apiario, make_arnia, db):
    """Retired hives do not hold an apiary back."""
    apiario = make_apiario()
    retired = make_arnia(apiario=apiario)
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (retired["id_arnia"],)
    )

    response = admin.delete(f"/api/admin/apiari/{apiario['id_apiario']}")

    assert response.status_code == 200
    db.execute(
        "SELECT attivo, data_disattivazione FROM apiari WHERE id_apiario = %s",
        (apiario["id_apiario"],),
    )
    row = db.fetchone()
    assert row["attivo"] is False
    assert row["data_disattivazione"] is not None


@pytest.mark.parametrize("how", ["delete", "put"])
def test_an_apiario_with_active_hives_cannot_be_retired(
    admin, make_apiario, make_arnia, db, how
):
    """Both ways of retiring it go through the same rule, and the hives stay put."""
    apiario = make_apiario()
    arnia = make_arnia(apiario=apiario)
    path = f"/api/admin/apiari/{apiario['id_apiario']}"

    if how == "delete":
        response = admin.delete(path)
    else:
        response = admin.put(path, json={"attivo": False})

    assert response.status_code == 409
    db.execute(
        "SELECT a.attivo, h.id_apiario FROM apiari a JOIN arnie h USING (id_apiario)"
        " WHERE h.id_arnia = %s",
        (arnia["id_arnia"],),
    )
    assert dict(db.fetchone()) == {"attivo": True, "id_apiario": apiario["id_apiario"]}


def test_an_apiario_is_revived(admin, make_apiario):
    apiario = make_apiario(attivo=False)

    response = admin.put(
        f"/api/admin/apiari/{apiario['id_apiario']}", json={"attivo": True}
    )

    assert response.status_code == 200
    assert response.json()["attivo"] is True
    assert response.json()["data_disattivazione"] is None


# ============================================
# Hives, through the admin routes
# ============================================


def test_a_hive_is_created_in_an_apiario(admin, make_apiario, db):
    db.execute("INSERT INTO nodi (id_nodo) VALUES ('NODE-AP')")
    apiario = make_apiario()

    response = admin.post(
        "/api/admin/arnie",
        json={
            "id_nodo": "NODE-AP",
            "id_sensore_fisico": "S1",
            "id_apiario": apiario["id_apiario"],
        },
    )

    assert response.status_code == 200
    assert response.json()["id_apiario"] == apiario["id_apiario"]


@pytest.mark.parametrize(
    "attivo, expected",
    [(None, 404), (False, 400)],
    ids=["unknown", "retired"],
)
def test_a_hive_is_not_created_in_an_apiario_it_cannot_go_to(
    admin, make_apiario, db, attivo, expected
):
    """An unknown apiary is named as such, not reported as a missing node."""
    db.execute("INSERT INTO nodi (id_nodo) VALUES ('NODE-AP')")
    target = 999999 if attivo is None else make_apiario(attivo=attivo)["id_apiario"]

    response = admin.post(
        "/api/admin/arnie",
        json={"id_nodo": "NODE-AP", "id_sensore_fisico": "S1", "id_apiario": target},
    )

    assert response.status_code == expected
    assert "Apiario" in response.json()["detail"]


def test_an_admin_moves_a_hive_into_any_apiario(admin, make_apiario, make_arnia):
    """No visibility rule for admins: they see every apiary."""
    arnia, apiario = make_arnia(), make_apiario()

    response = admin.put(
        f"/api/admin/arnie/{arnia['id_arnia']}",
        json={"id_apiario": apiario["id_apiario"]},
    )

    assert response.status_code == 200
    assert response.json()["id_apiario"] == apiario["id_apiario"]


def test_the_admin_hive_list_filters_by_apiario(admin, make_apiario, make_arnia):
    apiario = make_apiario()
    inside = make_arnia(apiario=apiario)
    make_arnia()

    body = admin.get(f"/api/admin/arnie?id_apiario={apiario['id_apiario']}").json()

    assert [a["id_arnia"] for a in body] == [inside["id_arnia"]]
