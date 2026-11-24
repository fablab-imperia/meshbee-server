"""Which API failures reach the error reporter (#56), and with what.

A 500 is a fault and is reported once, with the route template and the user's
id. Every 4xx is the client's business and is not.
"""

import pytest
from fastapi.testclient import TestClient

from api import main
from api.auth import create_access_token


def bearer(user) -> dict:
    """A real access token, so `get_current_user` runs and names the user."""
    return {"Authorization": f"Bearer {create_access_token({'sub': user['email']})}"}


def boom(*args, **kwargs):
    raise RuntimeError("relation does not exist")


def test_a_500_is_reported_once_with_route_operation_and_user(
    client, reporter, make_utente, monkeypatch
):
    user = make_utente()
    monkeypatch.setattr(main.arnie_service, "list_for_utente", boom)

    response = client.get("/api/user/arnie", headers=bearer(user))

    assert response.status_code == 500
    assert response.json() == {"detail": "Errore interno del server"}
    [(exc, context, person_id)] = reporter.reports
    assert isinstance(exc, RuntimeError)
    assert context == {
        "method": "GET",
        "route": "/api/user/arnie",
        "operation": "recupero arnie utente",
    }
    assert person_id == str(user["id_utente"])


def test_the_route_is_the_template_not_the_path(
    client, reporter, make_utente, make_arnia, monkeypatch
):
    """Reports for /api/user/arnie/7 and /8 group together."""
    user = make_utente()
    arnia = make_arnia(apiario=user)
    monkeypatch.setattr(main.arnie_service, "get_arnia", boom)

    response = client.get(f"/api/user/arnie/{arnia['id_arnia']}", headers=bearer(user))

    assert response.status_code == 500
    [(_, context, _)] = reporter.reports
    assert context["route"] == "/api/user/arnie/{id_arnia}"


def test_a_crash_outside_db_operation_is_reported_and_answered_500(
    client, reporter, make_utente, monkeypatch
):
    user = make_utente()
    monkeypatch.setattr(main, "require_arnia_access", boom)
    # Starlette re-raises after the handler; the test client would pass it on.
    tolerant = TestClient(main.app, raise_server_exceptions=False)

    response = tolerant.get("/api/user/arnie/1", headers=bearer(user))

    assert response.status_code == 500
    assert response.json() == {"detail": "Errore interno del server"}
    [(exc, context, person_id)] = reporter.reports
    assert isinstance(exc, RuntimeError)
    assert context == {"method": "GET", "route": "/api/user/arnie/{id_arnia}"}
    assert person_id == str(user["id_utente"])


def test_no_email_or_token_reaches_a_report(client, reporter, make_utente, monkeypatch):
    user = make_utente()
    monkeypatch.setattr(main.arnie_service, "list_for_utente", boom)

    client.get("/api/user/arnie", headers=bearer(user))

    [(_, context, person_id)] = reporter.reports
    sent = repr(context) + repr(person_id)
    assert user["email"] not in sent
    assert "Bearer" not in sent


@pytest.mark.parametrize(
    "method, url, body, signed_in, expected",
    [
        ("GET", "/api/user/arnie", None, False, {401}),  # no credentials
        ("GET", "/api/user/arnie?limit=-1", None, True, {422}),  # validation
        ("GET", "/api/user/arnie/999999", None, True, {403, 404}),  # no such arnia
        (
            "POST",
            "/api/auth/login",
            {"email": "x@y.it", "password": "nopenope"},
            False,
            {401},
        ),
    ],
)
def test_client_errors_are_not_reported(
    client, reporter, make_utente, method, url, body, signed_in, expected
):
    headers = bearer(make_utente()) if signed_in else {}

    response = client.request(method, url, json=body, headers=headers)

    assert response.status_code in expected
    assert reporter.reports == []


def test_a_conflict_is_not_reported(as_user, reporter, make_utente):
    """A 409 out of db_operation: a service outcome, not a fault."""
    existing = make_utente()
    admin = as_user(make_utente(ruolo="admin"))

    response = admin.post(
        "/api/admin/utenti",
        json={
            "email": existing["email"],
            "nome": "N",
            "cognome": "C",
            "password": "secret123",
        },
    )

    assert response.status_code == 409
    assert reporter.reports == []
