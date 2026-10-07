"""The authentication endpoints in api/main.py."""
from sqlalchemy.exc import OperationalError
import pytest

from api.auth import decode_token


@pytest.fixture
def utente(make_utente, password_hash):
    """An active user whose stored hash matches `known_password`."""
    return make_utente(password_hash=password_hash)


# ============================================
# POST /api/auth/login
# ============================================


def test_login_returns_a_usable_token_pair(client, utente, known_password):
    """Valid credentials yield an access and a refresh token for that user."""
    response = client.post(
        "/api/auth/login", json={"email": utente["email"], "password": known_password}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_token(body["access_token"])["sub"] == utente["email"]
    assert decode_token(body["access_token"])["type"] == "access"
    assert decode_token(body["refresh_token"])["type"] == "refresh"


def test_login_never_returns_the_password_hash(client, utente, known_password):
    """The login response carries tokens only, never anything from the utenti row."""
    response = client.post(
        "/api/auth/login", json={"email": utente["email"], "password": known_password}
    )

    assert set(response.json()) == {"access_token", "refresh_token", "token_type"}


def test_login_rejects_a_wrong_password(client, utente):
    """A bad password is a 401, not a 500 or a token."""
    response = client.post(
        "/api/auth/login", json={"email": utente["email"], "password": "wrong-password"}
    )

    assert response.status_code == 401


def test_login_rejects_an_unknown_email(client, known_password):
    """An account that does not exist gets the same 401 as a wrong password."""
    response = client.post(
        "/api/auth/login", json={"email": "nobody@example.org", "password": known_password}
    )

    assert response.status_code == 401


def test_login_rejects_a_deactivated_account(client, make_utente, password_hash, known_password):
    """Deactivating a user blocks login even with the correct password."""
    inactive = make_utente(password_hash=password_hash, attivo=False)

    response = client.post(
        "/api/auth/login", json={"email": inactive["email"], "password": known_password}
    )

    assert response.status_code == 401


def test_login_does_not_distinguish_unknown_from_wrong(client, utente, known_password):
    """Both failures return the same message, so the endpoint is not a user oracle."""
    wrong = client.post(
        "/api/auth/login", json={"email": utente["email"], "password": "wrong-password"}
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@example.org", "password": known_password}
    )

    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_email_is_case_insensitive(client, utente, known_password):
    """
    Addresses are stored lowercase by UserBase, and UserLogin normalises the
    same way, so the casing a user types does not matter.
    """
    response = client.post(
        "/api/auth/login",
        json={"email": utente["email"].upper(), "password": known_password},
    )

    assert response.status_code == 200


def test_login_ignores_surrounding_whitespace(client, utente, known_password):
    """A pasted address with stray spaces still matches."""
    response = client.post(
        "/api/auth/login",
        json={"email": f"  {utente['email']}  ", "password": known_password},
    )

    assert response.status_code == 200


def test_a_malformed_login_email_fails_authentication_not_validation(client, known_password):
    """
    UserLogin normalises but does not validate the format.

    Garbage in the email field must look like a failed login (401), not a
    validation error (422) that tells a caller which field was malformed.
    """
    response = client.post(
        "/api/auth/login", json={"email": "not-an-email", "password": known_password}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("payload", [{}, {"email": "a@b.org"}, {"password": "x"}])
def test_login_requires_both_fields(client, payload):
    """A malformed body is rejected by validation before any query runs."""
    assert client.post("/api/auth/login", json=payload).status_code == 422


# ============================================
# GET /api/auth/me
# ============================================


def test_me_returns_the_authenticated_user(as_user, utente):
    """The endpoint echoes the user resolved from the token."""
    response = as_user(utente).get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == utente["email"]
    assert response.json()["id_utente"] == utente["id_utente"]


def test_me_never_exposes_the_password_hash(as_user, utente):
    """UserResponse has no password_hash field — confirm none leaks through."""
    assert "password_hash" not in as_user(utente).get("/api/auth/me").json()


# ============================================
# Database outage
# ============================================


def test_login_during_a_database_outage_is_service_unavailable(client, fake_db, known_password):
    """
    An unreachable database answers 503, not 401.

    A 401 would tell the user their password is wrong and send the client
    straight back to the login form, retrying against a database in trouble.
    """
    from api import auth
    from api import main

    outage = OperationalError("SELECT 1", {}, Exception("could not connect to server"))
    fake_db(auth, error=outage)
    fake_db(main, error=outage)

    response = client.post(
        "/api/auth/login", json={"email": "a@b.org", "password": known_password}
    )

    assert response.status_code == 503
