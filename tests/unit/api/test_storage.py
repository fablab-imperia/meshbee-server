"""The request body limit (api/storage.py), on a minimal app of its own."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.storage import BodySizeLimitMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=10)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    return TestClient(app)


def test_a_body_within_the_limit_reaches_the_route(client):
    response = client.post("/echo", content=b"x" * 10)

    assert response.json() == {"size": 10}


def test_a_declared_oversized_body_is_refused_before_it_is_read(client):
    """FastAPI would otherwise spool the whole upload before any check ran."""
    response = client.post("/echo", content=b"x" * 11)

    assert response.status_code == 413
    assert "MB" in response.json()["detail"]


def test_an_oversized_body_without_a_length_is_refused_as_it_arrives(client):
    """Chunked: no Content-Length to look at, so the bytes are counted."""

    def chunks():
        yield b"x" * 6
        yield b"x" * 6

    response = client.post("/echo", content=chunks())

    assert response.status_code == 413
