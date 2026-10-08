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
    admin, make_utente, make_apiario, make_arnia
):
    """Neither the default nor an apiary with hives in it, even for an admin."""
    utente = make_utente()
    full, empty = make_apiario(utente), make_apiario(utente)
    make_arnia(apiario=full)

    default_path = f"/api/admin/apiari/{utente['id_apiario_predefinito']}"
    assert admin.delete(default_path).status_code == 409
    assert admin.delete(f"/api/admin/apiari/{full['id_apiario']}").status_code == 409
    assert admin.delete(f"/api/admin/apiari/{empty['id_apiario']}").status_code == 200


def test_the_admin_hive_list_filters_by_apiario(
    admin, make_utente, make_apiario, make_arnia
):
    utente = make_utente()
    apiario = make_apiario(utente)
    inside = make_arnia(apiario=apiario)
    make_arnia(apiario=utente)

    body = admin.get(f"/api/admin/arnie?id_apiario={apiario['id_apiario']}").json()

    assert [(a["id_arnia"], a["id_apiario"]) for a in body] == [
        (inside["id_arnia"], apiario["id_apiario"])
    ]


# ============================================
# PUT /api/admin/nodi/{id_nodo}/proprietario
# ============================================


def assign(client, id_nodo, id_utente):
    return client.put(
        f"/api/admin/nodi/{id_nodo}/proprietario", json={"id_utente": id_utente}
    )


def hives_of(db, id_nodo):
    db.execute(
        "SELECT a.id_apiario, ap.id_utente_proprietario FROM arnie a"
        " LEFT JOIN apiari ap USING (id_apiario) WHERE a.id_nodo = %s",
        (id_nodo,),
    )
    return [tuple(row.values()) for row in db.fetchall()]


def test_assigning_a_node_puts_its_hives_in_the_owners_default(
    admin, make_utente, make_arnia, db
):
    utente = make_utente()
    arnia = make_arnia()

    response = assign(admin, arnia["id_nodo"], utente["id_utente"])

    assert response.status_code == 200
    assert response.json()["id_proprietario"] == utente["id_utente"]
    assert hives_of(db, arnia["id_nodo"]) == [
        (utente["id_apiario_predefinito"], utente["id_utente"])
    ]


def test_transferring_a_node_moves_its_hives_away_from_the_old_owners_shares(
    admin, as_user, make_utente, make_apiario, make_arnia, share, db
):
    """The new owner gets the hives in their Default; old shares do not follow."""
    old, new, guest = make_utente(), make_utente(), make_utente()
    shared = make_apiario(old)
    arnia = make_arnia(apiario=shared)
    share(guest["id_utente"], shared["id_apiario"], "viewer")

    assign(admin, arnia["id_nodo"], new["id_utente"])

    assert hives_of(db, arnia["id_nodo"]) == [
        (new["id_apiario_predefinito"], new["id_utente"])
    ]
    assert as_user(guest).get("/api/user/arnie").json() == []


def test_unassigning_a_node_hides_its_hives_from_the_former_owner(
    admin, as_user, make_utente, make_arnia, db
):
    utente = make_utente()
    arnia = make_arnia(apiario=utente)

    assign(admin, arnia["id_nodo"], None)

    assert hives_of(db, arnia["id_nodo"]) == [(None, None)]
    assert as_user(utente).get("/api/user/arnie").json() == []


def test_re_assigning_the_same_owner_keeps_their_arrangement(
    admin, make_utente, make_apiario, make_arnia, db
):
    """Hives the owner moved out of the Default stay where they put them."""
    utente = make_utente()
    orto = make_apiario(utente)
    arnia = make_arnia(apiario=orto)

    assign(admin, arnia["id_nodo"], utente["id_utente"])

    assert hives_of(db, arnia["id_nodo"]) == [(orto["id_apiario"], utente["id_utente"])]


# ============================================
# POST /api/admin/arnie: where a new hive goes
# ============================================


def create_hive(client, id_nodo, sensor="S1", **extra):
    return client.post(
        "/api/admin/arnie",
        json={"id_nodo": id_nodo, "id_sensore_fisico": sensor, **extra},
    )


def test_a_hive_of_an_owned_node_goes_in_the_owners_default(
    admin, make_utente, make_arnia
):
    utente = make_utente()
    existing = make_arnia(apiario=utente)

    response = create_hive(admin, existing["id_nodo"], "S-NEW")

    assert response.json()["id_apiario"] == utente["id_apiario_predefinito"]


def test_a_hive_can_be_created_in_another_apiario_of_the_node_owner(
    admin, make_utente, make_apiario, make_arnia
):
    utente = make_utente()
    orto = make_apiario(utente)
    existing = make_arnia(apiario=utente)

    response = create_hive(
        admin, existing["id_nodo"], "S-NEW", id_apiario=orto["id_apiario"]
    )

    assert response.json()["id_apiario"] == orto["id_apiario"]


def test_a_hive_cannot_be_created_in_someone_elses_apiario(
    admin, make_utente, make_arnia
):
    """A node's hives always belong to the node's owner."""
    existing = make_arnia(apiario=make_utente())

    response = create_hive(
        admin,
        existing["id_nodo"],
        "S-NEW",
        id_apiario=make_utente()["id_apiario_predefinito"],
    )

    assert response.status_code == 400


def test_a_hive_of_an_unassigned_node_stays_unassigned(admin, make_arnia, make_utente):
    existing = make_arnia()

    created = create_hive(admin, existing["id_nodo"], "S-NEW")
    refused = create_hive(
        admin,
        existing["id_nodo"],
        "S-OTHER",
        id_apiario=make_utente()["id_apiario_predefinito"],
    )

    assert created.json()["id_apiario"] is None
    assert refused.status_code == 400
