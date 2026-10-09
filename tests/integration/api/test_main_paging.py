"""Optional paging on the list routes: `limit`/`offset` in, `X-Total-Count` out."""

from datetime import datetime

import pytest

TOTAL = "x-total-count"

# Every list route that pages, and who calls it in `world`.
ROUTES = [
    ("admin", "/api/admin/utenti"),
    ("admin", "/api/admin/nodi"),
    ("admin", "/api/admin/arnie"),
    ("admin", "/api/admin/apiari"),
    ("admin", "/api/admin/letture"),
    ("admin", "/api/admin/attivita"),
    ("owner", "/api/user/arnie"),
    ("owner", "/api/user/apiari"),
    ("owner", "/api/user/arnie/{id_arnia}/letture"),
    ("owner", "/api/user/arnie/{id_arnia}/attivita"),
    ("owner", "/api/user/apiari/{id_apiario}/condivisioni"),
]


@pytest.fixture
def world(
    as_user, make_utente, make_apiario, make_arnia, make_lettura, make_attivita, share
):
    """
    At least two rows behind every route: an owner with two hives on two
    nodes, a second apiary, readings and activities on one hive, and two users it is shared with.
    """
    owner, admin = make_utente(), make_utente(ruolo="admin")
    make_apiario(owner)
    arnia = make_arnia(apiario=owner)
    make_arnia(id_nodo="NODE-PAGING-2", apiario=owner)  # a second node too
    for _ in range(3):
        make_lettura(arnia)
        make_attivita(arnia, owner)
    for _ in range(2):
        share(make_utente()["id_utente"], owner["id_apiario_predefinito"])
    users = {"owner": owner, "admin": admin}
    ids = {"id_arnia": arnia["id_arnia"], "id_apiario": owner["id_apiario_predefinito"]}

    def get(who, route, **params):
        return as_user(users[who]).get(route.format(**ids), params=params)

    return get


@pytest.mark.parametrize(("who", "route"), ROUTES)
def test_without_paging_parameters_a_list_is_whole_and_uncounted(world, who, route):
    """Clients that never page see the route exactly as it was."""
    response = world(who, route)

    assert response.status_code == 200
    assert len(response.json()) >= 2
    assert TOTAL not in response.headers


@pytest.mark.parametrize(("who", "route"), ROUTES)
def test_pages_walk_the_whole_list_once_and_count_it(world, who, route):
    whole = world(who, route).json()

    pages = [world(who, route, limit=1, offset=i) for i in range(len(whole))]

    assert [p.json() for p in pages] == [[row] for row in whole]
    assert {p.headers[TOTAL] for p in pages} == {str(len(whole))}


@pytest.mark.parametrize(("who", "route"), ROUTES)
def test_an_offset_past_the_end_is_an_empty_page_with_the_total(world, who, route):
    whole = world(who, route).json()

    response = world(who, route, offset=len(whole))

    assert response.status_code == 200
    assert response.json() == []
    assert response.headers[TOTAL] == str(len(whole))


def test_readings_that_share_a_timestamp_page_without_repeats(
    as_user, make_utente, make_arnia, make_lettura
):
    """The id breaks the tie, so the order is the same on every page."""
    owner = make_utente()
    arnia = make_arnia(apiario=owner)
    same = datetime(2026, 10, 1, 12, 0)
    ids = {make_lettura(arnia, timestamp=same)["id_lettura"] for _ in range(5)}
    client = as_user(owner)
    route = f"/api/user/arnie/{arnia['id_arnia']}/letture"
    params = {"data_inizio": "2026-09-01T00:00:00", "data_fine": "2026-11-01T00:00:00"}

    seen = [
        row["id_lettura"]
        for offset in (0, 2, 4)
        for row in client.get(
            route, params=params | {"limit": 2, "offset": offset}
        ).json()
    ]

    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(ids)


def test_an_offset_alone_keeps_the_routes_default_limit(world):
    response = world("admin", "/api/admin/letture", offset=1)

    assert response.status_code == 200
    assert len(response.json()) == int(response.headers[TOTAL]) - 1


@pytest.mark.parametrize(
    "params",
    [{"offset": -1}, {"limit": 0}, {"limit": 1001}],
    ids=["negative offset", "zero limit", "limit over the maximum"],
)
def test_out_of_range_paging_is_rejected(world, params):
    assert world("admin", "/api/admin/utenti", **params).status_code == 422


def test_the_total_is_readable_cross_origin(world, as_user, make_utente):
    """A browser on another origin only sees headers CORS exposes."""
    client = as_user(make_utente(ruolo="admin"))

    response = client.get(
        "/api/admin/utenti",
        params={"limit": 1},
        headers={"Origin": "https://app.example"},
    )

    assert TOTAL in response.headers["access-control-expose-headers"].lower()
