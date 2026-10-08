"""The /api/user/apiari endpoints, sharing, and apiaries through the hive endpoints.

An apiary belongs to one user and holds that user's hives; its owner shares it
with others as viewer, collaborator or manager. Who may call which route is
pinned in test_main_authz.py; these tests pin what the routes do.
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


def share_by_api(client, apiario, email, ruolo="viewer"):
    return client.post(
        f"/api/user/apiari/{apiario['id_apiario']}/condivisioni",
        json={"email": email, "ruolo": ruolo},
    )


# ============================================
# GET/POST /api/user/apiari
# ============================================


def test_a_user_lists_their_own_apiari_then_those_shared_with_them(
    as_user, make_utente, make_apiario, share
):
    utente, other = make_utente(), make_utente()
    mine = make_apiario(utente)
    theirs = make_apiario(other)
    make_apiario(other)  # not shared
    share(utente["id_utente"], theirs["id_apiario"], "collaborator")

    body = as_user(utente).get("/api/user/apiari").json()

    assert [(a["id_apiario"], a["accesso"], a["predefinito"]) for a in body] == [
        (utente["id_apiario_predefinito"], "owner", True),
        (mine["id_apiario"], "owner", False),
        (theirs["id_apiario"], "collaborator", False),
    ]


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


def test_a_shared_apiario_shows_the_callers_access(
    as_user, make_utente, make_apiario, share
):
    utente = make_utente()
    apiario = make_apiario(make_utente())
    share(utente["id_utente"], apiario["id_apiario"], "manager")

    body = as_user(utente).get(f"/api/user/apiari/{apiario['id_apiario']}").json()

    assert body["accesso"] == "manager"


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


def test_a_manager_edits_a_shared_apiario(as_user, make_utente, make_apiario, share):
    utente = make_utente()
    apiario = make_apiario(make_utente())
    share(utente["id_utente"], apiario["id_apiario"], "manager")

    response = as_user(utente).put(
        f"/api/user/apiari/{apiario['id_apiario']}", json={"posizione": "Nord"}
    )

    assert response.status_code == 200
    assert response.json()["posizione"] == "Nord"


def test_the_default_cannot_be_deleted(as_user, make_utente):
    """It is where the hives of newly assigned nodes land."""
    utente = make_utente()

    response = as_user(utente).delete(
        f"/api/user/apiari/{utente['id_apiario_predefinito']}"
    )

    assert response.status_code == 409


def test_an_apiario_with_active_hives_cannot_be_deleted(
    as_user, make_utente, make_apiario, make_arnia
):
    """Where each hive goes is the owner's decision, not a side effect."""
    utente = make_utente()
    apiario = make_apiario(utente)
    make_arnia(apiario=apiario)

    response = as_user(utente).delete(f"/api/user/apiari/{apiario['id_apiario']}")

    assert response.status_code == 409


def test_an_emptied_apiario_is_deleted_with_its_shares(
    as_user, make_utente, make_apiario, make_arnia, share, db
):
    """Retired hives, which no list shows, move to the Default instead of blocking."""
    utente = make_utente()
    apiario = make_apiario(utente)
    retired = make_arnia(apiario=apiario)
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (retired["id_arnia"],)
    )
    share(make_utente()["id_utente"], apiario["id_apiario"], "viewer")

    response = as_user(utente).delete(f"/api/user/apiari/{apiario['id_apiario']}")

    assert response.status_code == 200
    db.execute(
        "SELECT id_apiario FROM arnie WHERE id_arnia = %s", (retired["id_arnia"],)
    )
    assert db.fetchone()["id_apiario"] == utente["id_apiario_predefinito"]
    db.execute("SELECT count(*) AS n FROM utenti_apiari")
    assert db.fetchone()["n"] == 0


# ============================================
# Sharing: /api/user/apiari/{id_apiario}/condivisioni
# ============================================


def test_sharing_by_email_opens_the_apiario_and_its_hives(
    as_user, make_utente, make_apiario, make_arnia
):
    owner, guest = make_utente(), make_utente()
    apiario = make_apiario(owner)
    arnia = make_arnia(apiario=apiario)

    response = share_by_api(as_user(owner), apiario, guest["email"].upper(), "viewer")

    assert response.status_code == 200
    assert response.json()["id_utente"] == guest["id_utente"]
    # Nothing about the account beyond the email the owner already typed.
    assert response.json().keys() == {
        "id_utente",
        "id_apiario",
        "ruolo",
        "data_condivisione",
        "email",
    }
    hives = as_user(guest).get("/api/user/arnie").json()
    assert [(a["id_arnia"], a["accesso"]) for a in hives] == [
        (arnia["id_arnia"], "viewer")
    ]


def test_the_owner_lists_who_the_apiario_is_shared_with(
    as_user, make_utente, make_apiario, share
):
    owner, guest = make_utente(), make_utente()
    apiario = make_apiario(owner)
    share(guest["id_utente"], apiario["id_apiario"], "collaborator")

    body = (
        as_user(owner)
        .get(f"/api/user/apiari/{apiario['id_apiario']}/condivisioni")
        .json()
    )

    assert [(s["email"], s["ruolo"]) for s in body] == [
        (guest["email"], "collaborator")
    ]


def test_sharing_again_changes_the_role(as_user, make_utente, make_apiario):
    owner, guest = make_utente(), make_utente()
    apiario = make_apiario(owner)
    client = as_user(owner)
    share_by_api(client, apiario, guest["email"], "viewer")

    response = share_by_api(client, apiario, guest["email"], "manager")

    assert response.json()["ruolo"] == "manager"
    body = client.get(f"/api/user/apiari/{apiario['id_apiario']}/condivisioni").json()
    assert len(body) == 1


def test_sharing_with_an_unknown_email_is_not_found(as_user, make_utente, make_apiario):
    owner = make_utente()

    response = share_by_api(as_user(owner), make_apiario(owner), "nobody@example.org")

    assert response.status_code == 404


def test_the_owner_cannot_share_with_themselves(as_user, make_utente, make_apiario):
    """Owning already allows everything; a role would only take something away."""
    owner = make_utente()

    response = share_by_api(as_user(owner), make_apiario(owner), owner["email"])

    assert response.status_code == 400


def test_a_role_is_changed_and_revoked(
    as_user, make_utente, make_apiario, make_arnia, share
):
    owner, guest = make_utente(), make_utente()
    apiario = make_apiario(owner)
    make_arnia(apiario=apiario)
    share(guest["id_utente"], apiario["id_apiario"], "viewer")
    path = f"/api/user/apiari/{apiario['id_apiario']}/condivisioni/{guest['id_utente']}"
    client = as_user(owner)

    changed = client.put(path, json={"ruolo": "collaborator"})
    revoked = client.delete(path)

    assert changed.json()["ruolo"] == "collaborator"
    assert revoked.status_code == 200
    assert as_user(owner).delete(path).status_code == 404
    # `as_user` switches the one test client, so the guest's view comes last.
    assert as_user(guest).get("/api/user/arnie").json() == []


# ============================================
# GET /api/user/arnie, with apiaries
# ============================================


def test_hives_keep_every_field_they_had_before_apiari(
    as_user, utente_con_arnia, make_lettura
):
    """Backward compatibility: the app reads these, apiaries only add to them."""
    utente, arnia = utente_con_arnia("viewer")
    make_lettura(arnia, temperatura="35.5")

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert ARNIA_FIELDS_BEFORE_APIARI <= row.keys()
    assert row["nome_apiario"] == "Default"
    assert row["accesso"] == "viewer"


def test_filtering_by_apiario(as_user, make_utente, make_apiario, make_arnia):
    utente = make_utente()
    apiario = make_apiario(utente)
    inside = make_arnia(apiario=apiario)
    make_arnia(apiario=utente)

    body = as_user(utente).get(f"/api/user/arnie?id_apiario={apiario['id_apiario']}")

    assert [a["id_arnia"] for a in body.json()] == [inside["id_arnia"]]


def test_filtering_by_an_apiario_not_shared_matches_nothing(
    as_user, make_utente, make_apiario, make_arnia
):
    """The filter narrows what the user can see; it never widens it."""
    utente = make_utente()
    theirs = make_apiario(make_utente())
    make_arnia(apiario=theirs)

    body = as_user(utente).get(f"/api/user/arnie?id_apiario={theirs['id_apiario']}")

    assert body.json() == []


# ============================================
# PUT /api/user/arnie/{id_arnia}/apiario
# ============================================


def move(client, arnia, id_apiario):
    return client.put(
        f"/api/user/arnie/{arnia['id_arnia']}/apiario", json={"id_apiario": id_apiario}
    )


def test_the_owner_moves_a_hive_between_their_apiari(
    as_user, make_utente, make_apiario, make_arnia
):
    utente = make_utente()
    orto = make_apiario(utente)
    arnia = make_arnia(apiario=utente)

    response = move(as_user(utente), arnia, orto["id_apiario"])

    assert response.status_code == 200
    assert response.json()["id_apiario"] == orto["id_apiario"]


def test_a_hive_moved_out_of_a_shared_apiario_is_no_longer_shared(
    as_user, make_utente, make_apiario, make_arnia, share
):
    """Access follows the apiary: moving a hive is how an owner un-shares it."""
    owner, guest = make_utente(), make_utente()
    shared, private = make_apiario(owner), make_apiario(owner)
    arnia = make_arnia(apiario=shared)
    share(guest["id_utente"], shared["id_apiario"], "manager")

    move(as_user(owner), arnia, private["id_apiario"])

    assert as_user(guest).get("/api/user/arnie").json() == []


@pytest.mark.parametrize("exists", [True, False])
def test_a_hive_cannot_be_moved_into_someone_elses_apiario(
    as_user, make_utente, make_apiario, make_arnia, exists
):
    """Same 400 whether it exists or not: the answer must not reveal it."""
    utente = make_utente()
    arnia = make_arnia(apiario=utente)
    target = make_apiario(make_utente())["id_apiario"] if exists else 999999

    response = move(as_user(utente), arnia, target)

    assert response.status_code == 400
    assert response.json()["detail"] == "Apiario non accessibile"


def test_an_admin_moves_a_hive_only_within_its_owners_apiari(
    as_user, make_utente, make_apiario, make_arnia
):
    """Admins may act on any hive, but a hive stays with its owner."""
    admin, owner = make_utente(ruolo="admin"), make_utente()
    arnia = make_arnia(apiario=owner)
    client = as_user(admin)

    assert move(client, arnia, make_apiario(owner)["id_apiario"]).status_code == 200
    assert move(client, arnia, admin["id_apiario_predefinito"]).status_code == 400


def test_an_unassigned_hive_cannot_be_moved(as_user, make_utente, make_arnia):
    """It has no owner yet: assign its node first."""
    admin = make_utente(ruolo="admin")

    response = move(as_user(admin), make_arnia(), admin["id_apiario_predefinito"])

    assert response.status_code == 400


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
