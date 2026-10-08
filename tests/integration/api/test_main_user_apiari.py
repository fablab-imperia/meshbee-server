"""The /api/user/apiari endpoints, and apiaries as seen through the hive endpoints.

Access is per hive: these tests pin that an apiary never shows a user more
than the hives they were granted, and that a client unaware of apiaries keeps
working exactly as before.
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
    """An arnia in the given apiary, granted to the given user."""

    def _make(utente, apiario, permessi="read"):
        arnia = make_arnia(apiario=apiario)
        grant_access(utente["id_utente"], arnia["id_arnia"], permessi)
        return arnia

    return _make


# ============================================
# GET /api/user/apiari
# ============================================


def test_listing_returns_only_apiari_holding_the_users_hives(
    as_user, make_utente, make_apiario, make_arnia, hive_in
):
    utente, mine, other = make_utente(), make_apiario(), make_apiario()
    hive_in(utente, mine)
    make_arnia(apiario=other)

    body = as_user(utente).get("/api/user/apiari").json()

    assert [a["id_apiario"] for a in body] == [mine["id_apiario"]]


def test_admins_list_every_active_apiario(as_user, make_utente, make_apiario):
    first, second = make_apiario(), make_apiario()
    make_apiario(attivo=False)

    body = as_user(make_utente(ruolo="admin")).get("/api/user/apiari").json()

    assert {a["id_apiario"] for a in body} == {
        first["id_apiario"],
        second["id_apiario"],
    }


def test_detail_returns_the_apiario(as_user, make_utente, make_apiario, hive_in):
    utente, apiario = make_utente(), make_apiario(nome_apiario="Collina")
    hive_in(utente, apiario)

    response = as_user(utente).get(f"/api/user/apiari/{apiario['id_apiario']}")

    assert response.status_code == 200
    assert response.json()["nome_apiario"] == "Collina"


# ============================================
# GET /api/user/arnie, with apiaries
# ============================================


def test_hives_carry_their_apiario(as_user, make_utente, make_apiario, hive_in):
    utente, apiario = make_utente(), make_apiario(nome_apiario="Collina")
    hive_in(utente, apiario)

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert row["id_apiario"] == apiario["id_apiario"]
    assert row["nome_apiario"] == "Collina"


def test_hives_keep_every_field_they_had_before_apiari(
    as_user, utente_con_arnia, make_lettura
):
    """Backward compatibility: the app reads these, apiaries only add to them."""
    utente, arnia = utente_con_arnia("read")
    make_lettura(arnia, temperatura="35.5")

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert ARNIA_FIELDS_BEFORE_APIARI <= row.keys()
    assert row["id_apiario"] is None
    assert row["nome_apiario"] is None


def test_filtering_by_apiario_still_shows_only_the_users_hives(
    as_user, make_utente, make_apiario, make_arnia, hive_in
):
    """
    Being able to see an apiary does not open every hive in it: the filter
    narrows the user's list, it does not replace the association.
    """
    utente, apiario, elsewhere = make_utente(), make_apiario(), make_apiario()
    mine = hive_in(utente, apiario)
    make_arnia(apiario=apiario)  # same apiary, someone else's
    hive_in(utente, elsewhere)

    body = as_user(utente).get(f"/api/user/arnie?id_apiario={apiario['id_apiario']}")

    assert [a["id_arnia"] for a in body.json()] == [mine["id_arnia"]]


# ============================================
# PUT /api/user/arnie/{id_arnia}, moving a hive
# ============================================


def put_arnia(client, arnia, body):
    return client.put(f"/api/user/arnie/{arnia['id_arnia']}", json=body)


def test_an_update_that_omits_the_apiario_leaves_it(
    as_user, make_utente, make_apiario, hive_in
):
    """What every existing client sends: it must never take a hive out of its apiary."""
    utente, apiario = make_utente(), make_apiario()
    arnia = hive_in(utente, apiario, "write")

    response = put_arnia(as_user(utente), arnia, {"nome_arnia": "Nuovo nome"})

    assert response.status_code == 200
    assert response.json()["id_apiario"] == apiario["id_apiario"]


def test_an_explicit_null_takes_the_hive_out_of_its_apiario(
    as_user, make_utente, make_apiario, hive_in
):
    utente = make_utente()
    arnia = hive_in(utente, make_apiario(), "write")

    response = put_arnia(as_user(utente), arnia, {"id_apiario": None})

    assert response.status_code == 200
    assert response.json()["id_apiario"] is None


def test_a_user_moves_a_hive_into_an_apiario_they_can_see(
    as_user, make_utente, make_apiario, hive_in
):
    utente, here, there = make_utente(), make_apiario(), make_apiario()
    arnia = hive_in(utente, here, "write")
    hive_in(utente, there)  # read on another hive is enough to see `there`

    response = put_arnia(as_user(utente), arnia, {"id_apiario": there["id_apiario"]})

    assert response.status_code == 200
    assert response.json()["id_apiario"] == there["id_apiario"]


@pytest.mark.parametrize("exists", [True, False])
def test_a_user_cannot_move_a_hive_into_an_apiario_they_cannot_see(
    as_user, make_utente, make_apiario, hive_in, exists
):
    """Same 400 whether the apiary exists or not: the answer must not reveal it."""
    utente = make_utente()
    arnia = hive_in(utente, None, "write")
    target = make_apiario()["id_apiario"] if exists else 999999

    response = put_arnia(as_user(utente), arnia, {"id_apiario": target})

    assert response.status_code == 400
    assert response.json()["detail"] == "Apiario non accessibile"


def test_a_hive_cannot_be_moved_into_a_retired_apiario(
    as_user, make_utente, make_apiario, hive_in
):
    utente, retired = make_utente(), make_apiario(attivo=False)
    arnia = hive_in(utente, None, "write")
    hive_in(utente, retired)

    response = put_arnia(as_user(utente), arnia, {"id_apiario": retired["id_apiario"]})

    assert response.status_code == 400
