"""Tests for GET /health (api/main.py)."""

from sqlalchemy.exc import OperationalError

from api import main

# What psycopg2 says when the database refuses the connection — the kind of
# text that must not reach an anonymous caller.
REFUSAL = (
    'connection to server at "postgres" (172.18.0.2), port 5432 failed: '
    'FATAL:  password authentication failed for user "beehive_user"'
)


def test_a_reachable_database_is_healthy(client):
    body = client.get("/health").json()

    assert body["status"] == "healthy"
    assert body["database"] == "connected"


def test_an_outage_is_reported_without_its_details(client, fake_db, caplog):
    """
    Anyone can call /health, so the verdict is public but the reason is not.

    The database's error names its host, port and user; it goes to the log,
    where the operator looks, and stays out of the response body.
    """
    fake_db(main, error=OperationalError("SELECT 1", {}, Exception(REFUSAL)))

    response = client.get("/health")

    assert response.status_code == 200  # by design: the verdict is in the body
    assert response.json()["status"] == "unhealthy"
    assert "beehive_user" not in response.text
    assert "postgres" not in response.text
    assert "beehive_user" in caplog.text
