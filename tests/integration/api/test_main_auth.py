"""The authentication endpoints in api/main.py."""

import pytest
from sqlalchemy.exc import OperationalError

from api.auth import create_refresh_token, decode_token


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
        "/api/auth/login",
        json={"email": "nobody@example.org", "password": known_password},
    )

    assert response.status_code == 401


def test_login_rejects_a_deactivated_account(
    client, make_utente, password_hash, known_password
):
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
        "/api/auth/login",
        json={"email": "nobody@example.org", "password": known_password},
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


def test_a_malformed_login_email_fails_authentication_not_validation(
    client, known_password
):
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
# POST /api/auth/refresh and /api/auth/logout
# ============================================


@pytest.fixture
def login(client, utente, known_password):
    """Log `utente` in for real and return the token pair."""

    def _login():
        response = client.post(
            "/api/auth/login",
            json={"email": utente["email"], "password": known_password},
        )
        assert response.status_code == 200
        return response.json()

    return _login


def refresh(client, token):
    return client.post("/api/auth/refresh", json={"refresh_token": token})


def test_login_records_a_session(client, db, utente, login):
    """The refresh token is stored as a hash, with who asked for it."""
    login()

    db.execute(
        "SELECT * FROM token_sessione WHERE id_utente = %s", (utente["id_utente"],)
    )
    (row,) = db.fetchall()
    assert row["revocato"] is False
    assert row["user_agent"] == "testclient"


def test_behind_caddy_a_session_records_the_users_address(
    client, db, utente, known_password
):
    """
    With FORWARDED_ALLOW_IPS="*" (both compose files), uvicorn takes the client
    from Caddy's X-Forwarded-For, and the session must record that, not Caddy.
    """
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from api import main

    behind_caddy = TestClient(ProxyHeadersMiddleware(main.app, trusted_hosts="*"))
    behind_caddy.post(
        "/api/auth/login",
        json={"email": utente["email"], "password": known_password},
        headers={"X-Forwarded-For": "203.0.113.7"},
    )

    db.execute(
        "SELECT ip_address FROM token_sessione WHERE id_utente = %s",
        (utente["id_utente"],),
    )
    assert db.fetchone()["ip_address"] == "203.0.113.7"


def test_refresh_returns_a_new_working_pair(client, utente, login):
    tokens = login()

    response = refresh(client, tokens["refresh_token"])

    assert response.status_code == 200
    fresh = response.json()
    assert fresh["refresh_token"] != tokens["refresh_token"]
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {fresh['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id_utente"] == utente["id_utente"]


def test_a_refresh_token_works_once(client, login):
    tokens = login()
    refresh(client, tokens["refresh_token"])

    response = refresh(client, tokens["refresh_token"])

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_reusing_a_refresh_token_kills_the_rotated_one_too(client, login):
    """Reuse means a copy is out there: every session of the account ends."""
    tokens = login()
    fresh = refresh(client, tokens["refresh_token"]).json()

    refresh(client, tokens["refresh_token"])

    assert refresh(client, fresh["refresh_token"]).status_code == 401


def test_an_access_token_is_not_a_refresh_token(client, login):
    assert refresh(client, login()["access_token"]).status_code == 401


def test_a_garbage_refresh_token_is_unauthorized(client):
    assert refresh(client, "not-a-jwt").status_code == 401


def test_a_well_signed_but_unrecorded_refresh_token_is_unauthorized(client, utente):
    """Signing alone no longer suffices: the token must have been issued and kept."""
    token = create_refresh_token({"sub": utente["email"]})

    assert refresh(client, token).status_code == 401


def test_logout_revokes_the_refresh_token(client, login):
    tokens = login()

    response = client.post(
        "/api/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 200
    assert refresh(client, tokens["refresh_token"]).status_code == 401


@pytest.mark.parametrize("token", ["not-a-jwt", "access"])
def test_logout_answers_the_same_for_any_token(client, login, token):
    """Logout is no oracle for which tokens are live."""
    if token == "access":
        token = login()["access_token"]

    response = client.post("/api/auth/logout", json={"refresh_token": token})

    assert response.status_code == 200


def test_deactivating_a_user_stops_their_refresh(
    client, as_user, make_utente, utente, login
):
    tokens = login()
    admin = make_utente(ruolo="admin")

    as_user(admin).delete(f"/api/admin/utenti/{utente['id_utente']}")

    assert refresh(client, tokens["refresh_token"]).status_code == 401


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


def test_login_during_a_database_outage_is_service_unavailable(
    client, fake_db, known_password
):
    """
    An unreachable database answers 503, not 401.

    A 401 would tell the user their password is wrong and send the client
    straight back to the login form, retrying against a database in trouble.
    """
    from api import auth, main

    outage = OperationalError("SELECT 1", {}, Exception("could not connect to server"))
    fake_db(auth, error=outage)
    fake_db(main, error=outage)

    response = client.post(
        "/api/auth/login", json={"email": "a@b.org", "password": known_password}
    )

    assert response.status_code == 503
