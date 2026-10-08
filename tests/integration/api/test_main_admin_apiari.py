"""The /api/admin/apiari endpoints: any user's apiaries, under the owner's rules."""

import pytest


@pytest.fixture
def admin(as_user, make_utente):
    """A client authenticated as an admin."""
    return as_user(make_utente(ruolo="admin"))


def test_an_admin_creates_an_apiario_for_a_user(admin, make_utente):
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
    assert body["id_utente_proprietario"] == owner["id_utente"]
    assert body["predefinito"] is False


def test_an_unknown_owner_is_not_found(admin):
    response = admin.post(
        "/api/admin/apiari",
        json={"nome_apiario": "Collina", "id_utente_proprietario": 999999},
    )

    assert response.status_code == 404


def test_an_owner_is_required(admin):
    """There is no unowned apiary: it would be nobody's grouping."""
    response = admin.post("/api/admin/apiari", json={"nome_apiario": "Collina"})

    assert response.status_code == 422


def test_coordinates_out_of_range_are_refused(admin, make_utente):
    """The same bounds as a hive's, from limits.py."""
    response = admin.post(
        "/api/admin/apiari",
        json={
            "nome_apiario": "Collina",
            "latitudine": "91",
            "id_utente_proprietario": make_utente()["id_utente"],
        },
    )

    assert response.status_code == 422


def test_the_admin_list_spans_every_user_and_filters_by_one(
    admin, make_utente, make_apiario
):
    first, second = make_utente(), make_utente()
    extra = make_apiario(second)

    everyone = {a["id_apiario"] for a in admin.get("/api/admin/apiari").json()}
    one = admin.get(f"/api/admin/apiari?id_utente={second['id_utente']}").json()

    assert {
        first["id_apiario_predefinito"],
        second["id_apiario_predefinito"],
        extra["id_apiario"],
    } <= everyone
    assert [a["id_apiario"] for a in one] == [
        second["id_apiario_predefinito"],
        extra["id_apiario"],
    ]


def test_an_admin_edits_anyones_apiario(admin, make_utente, make_apiario):
    apiario = make_apiario(make_utente())

    response = admin.put(
        f"/api/admin/apiari/{apiario['id_apiario']}", json={"posizione": "Nord"}
    )

    assert response.status_code == 200
    assert response.json()["posizione"] == "Nord"


def test_an_unknown_apiario_is_not_found(admin):
    assert admin.get("/api/admin/apiari/999999").status_code == 404
    assert admin.put("/api/admin/apiari/999999", json={}).status_code == 404
    assert admin.delete("/api/admin/apiari/999999").status_code == 404


def test_admins_follow_the_owners_delete_rules(
    admin, make_utente, make_apiario, make_arnia, grant_access
):
    """Neither the default nor an apiary with hives in it, even for an admin."""
    utente = make_utente()
    full, empty = make_apiario(utente), make_apiario(utente)
    grant_access(
        utente["id_utente"], make_arnia()["id_arnia"], id_apiario=full["id_apiario"]
    )

    assert (
        admin.delete(
            f"/api/admin/apiari/{utente['id_apiario_predefinito']}"
        ).status_code
        == 409
    )
    assert admin.delete(f"/api/admin/apiari/{full['id_apiario']}").status_code == 409
    assert admin.delete(f"/api/admin/apiari/{empty['id_apiario']}").status_code == 200


def test_the_admin_hive_list_filters_by_apiario(
    admin, make_utente, make_apiario, make_arnia, grant_access
):
    """The hives the apiary's owner has put in it, with that apiary on each."""
    utente = make_utente()
    apiario = make_apiario(utente)
    inside = make_arnia()
    grant_access(
        utente["id_utente"], inside["id_arnia"], id_apiario=apiario["id_apiario"]
    )
    grant_access(utente["id_utente"], make_arnia()["id_arnia"])

    body = admin.get(f"/api/admin/arnie?id_apiario={apiario['id_apiario']}").json()

    assert [(a["id_arnia"], a["id_apiario"]) for a in body] == [
        (inside["id_arnia"], apiario["id_apiario"])
    ]


def test_the_admin_hive_list_rejects_an_unknown_apiario(admin):
    assert admin.get("/api/admin/arnie?id_apiario=999999").status_code == 404
