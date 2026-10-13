"""Tests for the paging dependency and header (api/paging.py).

The routes are covered end to end in tests/integration/api/test_main_paging.py.
These pin the dependency's own rules on a bare app, without a database.
"""

import pytest
from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from api.paging import TOTAL_HEADER, page_items, paging_query
from meshbee_core.paging import Page, Paging


def client_for(dependency) -> TestClient:
    """An app with one route that echoes the Paging the dependency built."""
    app = FastAPI()

    @app.get("/")
    def echo(paging: Paging = Depends(dependency)):
        return {"limit": paging.limit, "offset": paging.offset, "total": paging.total}

    return TestClient(app)


def test_without_parameters_the_list_is_whole_and_uncounted():
    """A client that never pages costs no COUNT query and gets every row."""
    response = client_for(paging_query()).get("/")

    assert response.json() == {"limit": None, "offset": 0, "total": False}


@pytest.mark.parametrize("params", [{"limit": 5}, {"offset": 0}])
def test_either_parameter_asks_for_the_total(params):
    """
    Sending `limit` or `offset` is what marks a paging client.

    Even `offset=0`, the default value: the client is paging and needs the total
    to draw its controls, so this is about presence, not value.
    """
    response = client_for(paging_query()).get("/", params=params)

    assert response.json()["total"] is True


def test_an_offset_alone_keeps_the_routes_default_limit():
    """A route that capped its list before paging keeps that cap."""
    response = client_for(paging_query(1000, 10000)).get("/", params={"offset": 20})

    assert response.json() == {"limit": 1000, "offset": 20, "total": True}


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "many"}]
)
def test_out_of_range_parameters_are_refused(params):
    """The maximum is what bounds the size of one response."""
    response = client_for(paging_query(max_limit=100)).get("/", params=params)

    assert response.status_code == 422


def test_a_counted_page_carries_its_total_in_the_header():
    """The body stays a plain list; the total travels beside it."""
    response = Response()

    body = page_items(response, Page(items=[{"id": 1}], total=7))

    assert body == [{"id": 1}]
    assert response.headers[TOTAL_HEADER] == "7"


def test_a_total_of_zero_is_still_sent():
    """An empty list is a real answer: a falsy check would drop the header."""
    response = Response()

    page_items(response, Page(items=[], total=0))

    assert response.headers[TOTAL_HEADER] == "0"


def test_an_uncounted_page_sends_no_header():
    """No header unless the client asked, so non-paging clients see no change."""
    response = Response()

    page_items(response, Page(items=[{"id": 1}]))

    assert TOTAL_HEADER not in response.headers
