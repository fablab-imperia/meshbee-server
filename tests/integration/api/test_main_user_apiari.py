"""The /api/user/apiari endpoints, and apiaries as seen through the hive endpoints.

Apiaries are personal: every user starts with a Default that holds whatever
they are granted, and may create, edit, delete and move hives between their
own. These tests pin that a user's organisation never leaks into anyone
else's, and that a client unaware of apiaries keeps working as before.
"""

import pytest

# Every field `GET /api/user/arnie` returned before apiaries existed. The app
# reads these; losing one is a breaking change.
ARNIA_FIELDS_BEFORE_APIARI = {
    "id_arnia",
    "id_nodo",
    "id_sensore_fisico",
    "nome_arnia",
    "descrizione",
    "posizione",
    "latitudine",
    "longitudine",
    "data_installazione",
    "data_rimozione",
    "attiva",
    "metadati",
    "ultima_temperatura",
    "ultima_umidita",
    "ultimo_peso",
    "ultima_batteria",
    "ultimo_aggiornamento",
}


@pytest.fixture
def hive_in(make_arnia, grant_access):
    """An arnia granted to the user, in the given apiary of theirs (default: Default)."""

    def _make(utente, apiario=None, permessi="write"):
        arnia = make_arnia()
        grant_access(
            utente["id_utente"],
            arnia["id_arnia"],
            permessi,
            id_apiario=apiario["id_apiario"] if apiario else None,
        )
        return arnia

    return _make


# ============================================
# GET/POST /api/user/apiari
# ============================================


def test_a_user_lists_only_their_own_apiari(as_user, make_utente, make_apiario):
    utente, other = make_utente(), make_utente()
    mine = make_apiario(utente)
    make_apiario(other)

    body = as_user(utente).get("/api/user/apiari").json()

    assert [a["id_apiario"] for a in body] == [
        utente["id_apiario_predefinito"],
        mine["id_apiario"],
    ]
    assert [a["predefinito"] for a in body] == [True, False]


def test_admins_list_only_their_own_on_the_user_route(
    as_user, make_utente, make_apiario
):
    """The user route is personal for everyone; the admin view is /api/admin/apiari."""
    admin = make_utente(ruolo="admin")
    make_apiario(make_utente())

    body = as_user(admin).get("/api/user/apiari").json()

    assert [a["id_apiario"] for a in body] == [admin["id_apiario_predefinito"]]


def test_a_user_creates_an_apiario_of_their_own(as_user, make_utente):
    utente = make_utente()

    response = as_user(utente).post(
        "/api/user/apiari", json={"nome_apiario": "Orto", "latitudine": "45.1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id_utente_proprietario"] == utente["id_utente"]
    assert body["predefinito"] is False


def test_the_owner_cannot_be_chosen_on_the_user_route(as_user, make_utente):
    """An owner in the body is ignored: a user only ever creates their own."""
    utente, other = make_utente(), make_utente()

    response = as_user(utente).post(
        "/api/user/apiari",
        json={"nome_apiario": "Orto", "id_utente_proprietario": other["id_utente"]},
    )

    assert response.json()["id_utente_proprietario"] == utente["id_utente"]


# ============================================
# PUT/DELETE /api/user/apiari/{id_apiario}
# ============================================


def test_the_default_can_be_renamed(as_user, make_utente):
    utente = make_utente()

    response = as_user(utente).put(
        f"/api/user/apiari/{utente['id_apiario_predefinito']}",
        json={"nome_apiario": "Casa"},
    )

    assert response.status_code == 200
    assert response.json()["nome_apiario"] == "Casa"
    assert response.json()["predefinito"] is True


def test_the_default_cannot_be_deleted(as_user, make_utente):
    """It is where new grants land, so every user always has one."""
    utente = make_utente()

    response = as_user(utente).delete(
        f"/api/user/apiari/{utente['id_apiario_predefinito']}"
    )

    assert response.status_code == 409


def test_an_apiario_with_hives_cannot_be_deleted(
    as_user, make_utente, make_apiario, hive_in
):
    """Where each hive goes is the owner's decision, not a side effect."""
    utente = make_utente()
    apiario = make_apiario(utente)
    hive_in(utente, apiario, "read")

    response = as_user(utente).delete(f"/api/user/apiari/{apiario['id_apiario']}")

    assert response.status_code == 409


def test_an_emptied_apiario_is_deleted_and_revoked_hives_go_to_default(
    as_user, make_utente, make_apiario, make_arnia, grant_access, db
):
    """A revoked association is invisible to its user, so it cannot block them."""
    utente = make_utente()
    apiario = make_apiario(utente)
    revoked = make_arnia()
    grant_access(
        utente["id_utente"],
        revoked["id_arnia"],
        attivo=False,
        id_apiario=apiario["id_apiario"],
    )

    response = as_user(utente).delete(f"/api/user/apiari/{apiario['id_apiario']}")

    assert response.status_code == 200
    db.execute(
        "SELECT id_apiario FROM utenti_arnie WHERE id_arnia = %s",
        (revoked["id_arnia"],),
    )
    assert db.fetchone()["id_apiario"] == utente["id_apiario_predefinito"]
    db.execute(
        "SELECT count(*) AS n FROM apiari WHERE id_apiario = %s",
        (apiario["id_apiario"],),
    )
    assert db.fetchone()["n"] == 0


# ============================================
# GET /api/user/arnie, with apiaries
# ============================================


def test_hives_carry_the_callers_apiario(as_user, make_utente, make_apiario, hive_in):
    utente = make_utente()
    apiario = make_apiario(utente, nome_apiario="Orto")
    hive_in(utente, apiario)

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert row["id_apiario"] == apiario["id_apiario"]
    assert row["nome_apiario"] == "Orto"


def test_hives_keep_every_field_they_had_before_apiari(
    as_user, utente_con_arnia, make_lettura
):
    """Backward compatibility: the app reads these, apiaries only add to them."""
    utente, arnia = utente_con_arnia("read")
    make_lettura(arnia, temperatura="35.5")

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert ARNIA_FIELDS_BEFORE_APIARI <= row.keys()
    assert row["nome_apiario"] == "Default"


def test_a_shared_hive_sits_in_each_users_own_apiario(
    as_user, make_utente, make_apiario, make_arnia, grant_access
):
    """The point of per-user membership: two users, one hive, two apiaries."""
    first, second = make_utente(), make_utente()
    orto = make_apiario(second, nome_apiario="Orto")
    arnia = make_arnia()
    grant_access(first["id_utente"], arnia["id_arnia"])
    grant_access(second["id_utente"], arnia["id_arnia"], id_apiario=orto["id_apiario"])

    seen_by_first = as_user(first).get(f"/api/user/arnie/{arnia['id_arnia']}").json()
    seen_by_second = as_user(second).get(f"/api/user/arnie/{arnia['id_arnia']}").json()

    assert seen_by_first["nome_apiario"] == "Default"
    assert seen_by_second["nome_apiario"] == "Orto"


def test_filtering_by_apiario(as_user, make_utente, make_apiario, hive_in):
    utente = make_utente()
    apiario = make_apiario(utente)
    inside = hive_in(utente, apiario)
    hive_in(utente)

    body = as_user(utente).get(f"/api/user/arnie?id_apiario={apiario['id_apiario']}")

    assert [a["id_arnia"] for a in body.json()] == [inside["id_arnia"]]


def test_filtering_by_someone_elses_apiario_matches_nothing(
    as_user, make_utente, make_apiario, make_arnia, grant_access, hive_in
):
    """Even with a hive in common, another user's apiary opens nothing."""
    utente, other = make_utente(), make_utente()
    theirs = make_apiario(other)
    shared = hive_in(utente)
    grant_access(
        other["id_utente"], shared["id_arnia"], id_apiario=theirs["id_apiario"]
    )

    body = as_user(utente).get(f"/api/user/arnie?id_apiario={theirs['id_apiario']}")

    assert body.json() == []


# ============================================
# PUT /api/user/arnie/{id_arnia}/apiario
# ============================================


def move(client, arnia, id_apiario):
    return client.put(
        f"/api/user/arnie/{arnia['id_arnia']}/apiario", json={"id_apiario": id_apiario}
    )


def test_a_user_moves_a_hive_between_their_apiari(
    as_user, make_utente, make_apiario, hive_in
):
    utente = make_utente()
    orto = make_apiario(utente)
    arnia = hive_in(utente)

    assert move(as_user(utente), arnia, orto["id_apiario"]).status_code == 200

    row = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}").json()
    assert row["id_apiario"] == orto["id_apiario"]


def test_moving_a_shared_hive_leaves_the_other_users_view_alone(
    as_user, make_utente, make_apiario, make_arnia, grant_access
):
    first, second = make_utente(), make_utente()
    arnia = make_arnia()
    grant_access(first["id_utente"], arnia["id_arnia"], "write")
    grant_access(second["id_utente"], arnia["id_arnia"])

    move(as_user(first), arnia, make_apiario(first)["id_apiario"])

    row = as_user(second).get(f"/api/user/arnie/{arnia['id_arnia']}").json()
    assert row["id_apiario"] == second["id_apiario_predefinito"]


@pytest.mark.parametrize("exists", [True, False])
def test_a_hive_cannot_be_moved_into_someone_elses_apiario(
    as_user, make_utente, make_apiario, hive_in, exists
):
    """Same 400 whether it exists or not: the answer must not reveal it."""
    utente = make_utente()
    arnia = hive_in(utente)
    target = make_apiario(make_utente())["id_apiario"] if exists else 999999

    response = move(as_user(utente), arnia, target)

    assert response.status_code == 400
    assert response.json()["detail"] == "Apiario non accessibile"


def test_moving_needs_an_association_even_for_an_admin(
    as_user, make_utente, make_apiario, make_arnia
):
    """An admin passes the gate, but has no apiary placement to change."""
    admin = make_utente(ruolo="admin")

    response = move(as_user(admin), make_arnia(), make_apiario(admin)["id_apiario"])

    assert response.status_code == 404


# ============================================
# Granting access
# ============================================


def test_a_new_grant_lands_in_the_default(as_user, make_utente, make_arnia, db):
    utente = make_utente()
    arnia = make_arnia()

    as_user(make_utente(ruolo="admin")).post(
        "/api/admin/utenti-arnie",
        json={"id_utente": utente["id_utente"], "id_arnia": arnia["id_arnia"]},
    )

    db.execute(
        "SELECT id_apiario FROM utenti_arnie WHERE id_arnia = %s", (arnia["id_arnia"],)
    )
    assert db.fetchone()["id_apiario"] == utente["id_apiario_predefinito"]


def test_a_grant_can_name_one_of_the_users_apiari(
    as_user, make_utente, make_apiario, make_arnia
):
    utente = make_utente()
    orto = make_apiario(utente)
    arnia = make_arnia()

    as_user(make_utente(ruolo="admin")).post(
        "/api/admin/utenti-arnie",
        json={
            "id_utente": utente["id_utente"],
            "id_arnia": arnia["id_arnia"],
            "id_apiario": orto["id_apiario"],
        },
    )

    row = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}").json()
    assert row["id_apiario"] == orto["id_apiario"]


def test_a_grant_cannot_use_another_users_apiario(
    as_user, make_utente, make_apiario, make_arnia
):
    utente = make_utente()

    response = as_user(make_utente(ruolo="admin")).post(
        "/api/admin/utenti-arnie",
        json={
            "id_utente": utente["id_utente"],
            "id_arnia": make_arnia()["id_arnia"],
            "id_apiario": make_apiario(make_utente())["id_apiario"],
        },
    )

    assert response.status_code == 400


def test_re_granting_keeps_the_hive_where_the_user_put_it(
    as_user, make_utente, make_apiario, make_arnia, grant_access
):
    """A re-level revives the association as it was, apiary included."""
    utente = make_utente()
    orto = make_apiario(utente)
    arnia = make_arnia()
    grant_access(utente["id_utente"], arnia["id_arnia"], id_apiario=orto["id_apiario"])

    as_user(make_utente(ruolo="admin")).post(
        "/api/admin/utenti-arnie",
        json={
            "id_utente": utente["id_utente"],
            "id_arnia": arnia["id_arnia"],
            "permessi": "write",
        },
    )

    row = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}").json()
    assert row["id_apiario"] == orto["id_apiario"]


def test_a_new_account_starts_with_a_default(as_user, make_utente):
    admin = as_user(make_utente(ruolo="admin"))
    created = admin.post(
        "/api/admin/utenti",
        json={
            "email": "new@b.org",
            "nome": "N",
            "cognome": "C",
            "password": "secret123",
        },
    ).json()

    body = admin.get(f"/api/admin/apiari?id_utente={created['id_utente']}").json()

    assert [(a["nome_apiario"], a["predefinito"]) for a in body] == [("Default", True)]
