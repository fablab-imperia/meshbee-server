"""Tests for authentication and JWT handling (api/auth.py)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from api import auth
from api.auth import (
    authenticate_user,
    check_user_arnia_access,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    get_current_admin_user,
    get_current_user,
)
from meshbee_core.security import get_password_hash

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def password_hash():
    """A real bcrypt hash of PASSWORD, computed once (12 rounds is deliberately slow)."""
    return get_password_hash(PASSWORD)


@pytest.fixture
def active_user(password_hash):
    """The `utenti` row shape returned by the login query."""
    return {
        "id_utente": 7,
        "email": "apicoltore@example.org",
        "password_hash": password_hash,
        "nome": "Giulia",
        "cognome": "Rossi",
        "ruolo": "user",
        "attivo": True,
    }


def bearer(token):
    """Wrap a raw token the way HTTPBearer hands it to the dependency."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ============================================
# JWT tokens
# ============================================


def test_access_token_round_trips_through_decode():
    """A freshly minted access token decodes back to its claims."""
    payload = decode_token(create_access_token({"sub": "apicoltore@example.org"}))

    assert payload["sub"] == "apicoltore@example.org"
    assert payload["type"] == "access"


def test_refresh_token_is_tagged_as_a_refresh_token():
    """The `type` claim is what keeps refresh tokens out of the access-token path."""
    payload = decode_token(create_refresh_token({"sub": "apicoltore@example.org"}))

    assert payload["type"] == "refresh"


def test_every_refresh_token_is_unique():
    """
    Two tokens for the same user in the same second still differ (the jti), so
    each one gets its own row in token_sessione.
    """
    first = create_refresh_token({"sub": "a@b.org"})
    second = create_refresh_token({"sub": "a@b.org"})

    assert first != second
    assert decode_token(first)["jti"] != decode_token(second)["jti"]


@pytest.mark.parametrize(
    "token, expected",
    [
        (lambda: create_refresh_token({"sub": "a@b.org"}), True),
        (lambda: create_access_token({"sub": "a@b.org"}), False),
        (lambda: "not-a-jwt", False),
        (
            lambda: create_access_token({"sub": "a@b.org"}, timedelta(minutes=-1)),
            False,
        ),
    ],
    ids=["refresh", "access", "garbage", "expired"],
)
def test_is_refresh_token(token, expected):
    assert auth.is_refresh_token(token()) is expected


def test_access_token_honours_an_explicit_lifetime():
    """An explicit expires_delta wins over the configured default."""
    payload = decode_token(
        create_access_token({"sub": "a@b.org"}, timedelta(minutes=15))
    )

    expected = datetime.now(UTC) + timedelta(minutes=15)
    assert (
        abs((datetime.fromtimestamp(payload["exp"], UTC) - expected).total_seconds())
        < 5
    )


def test_access_token_defaults_to_the_configured_lifetime(monkeypatch):
    """Without expires_delta the token lives for ACCESS_TOKEN_EXPIRE_MINUTES."""
    monkeypatch.setattr(auth.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 90)

    payload = decode_token(create_access_token({"sub": "a@b.org"}))

    expected = datetime.now(UTC) + timedelta(minutes=90)
    assert (
        abs((datetime.fromtimestamp(payload["exp"], UTC) - expected).total_seconds())
        < 5
    )


def test_refresh_token_uses_the_configured_lifetime(monkeypatch):
    """Refresh tokens are measured in days, from REFRESH_TOKEN_EXPIRE_DAYS."""
    monkeypatch.setattr(auth.settings, "REFRESH_TOKEN_EXPIRE_DAYS", 3)

    payload = decode_token(create_refresh_token({"sub": "a@b.org"}))

    expected = datetime.now(UTC) + timedelta(days=3)
    assert (
        abs((datetime.fromtimestamp(payload["exp"], UTC) - expected).total_seconds())
        < 5
    )


def test_decode_token_rejects_an_expired_token():
    """An expired token is refused rather than silently accepted."""
    expired = create_access_token({"sub": "a@b.org"}, timedelta(minutes=-1))

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(expired)


def test_decode_token_rejects_a_token_signed_with_another_key():
    """A token forged with a different secret does not validate against ours."""
    forged = jwt.encode(
        {"sub": "a@b.org", "type": "access"},
        "another-secret-at-least-32-bytes-long",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(forged)


def test_decode_token_rejects_an_unsigned_token():
    """`alg: none` carries no signature at all; it must never be accepted."""
    unsigned = jwt.encode({"sub": "a@b.org", "type": "access"}, None, algorithm="none")

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(unsigned)


def test_decode_token_accepts_only_the_configured_algorithm(monkeypatch):
    """Signed with our own secret but another HMAC: still refused (algorithm pinned)."""
    secret = "a-secret-long-enough-for-hs512-signing-0123456789-abcdefghijklmn"
    monkeypatch.setattr(auth.settings, "JWT_SECRET_KEY", SecretStr(secret))
    other_algorithm = jwt.encode(
        {"sub": "a@b.org", "type": "access"}, secret, algorithm="HS512"
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(other_algorithm)


# Issued by python-jose 3.5.0, the library before PyJWT, with the secret below:
# {"sub": "a@b.org", "type": "access", "exp": 4102444800} (year 2100), HS256.
TOKEN_FROM_PYTHON_JOSE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJhQGIub3JnIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6NDEwMjQ0NDgwMH0"
    ".AiEZmKKli5gQyzfzwHH5g--C7IuwdSxxbAiCaDX1seM"
)


def test_a_token_issued_before_the_switch_to_pyjwt_still_validates(monkeypatch):
    """Nobody is logged out by the library change: a JWT is a JWT."""
    monkeypatch.setattr(
        auth.settings,
        "JWT_SECRET_KEY",
        SecretStr("legacy-test-secret-at-least-32-bytes-long"),
    )

    payload = decode_token(TOKEN_FROM_PYTHON_JOSE)

    assert payload == {"sub": "a@b.org", "type": "access", "exp": 4102444800}


# ============================================
# Role dependencies
# ============================================


def test_get_current_active_user_passes_an_active_user_through(active_user):
    """An active user is returned unchanged."""
    assert get_current_active_user(active_user) is active_user


def test_get_current_active_user_rejects_an_inactive_user(active_user):
    """An inactive user is refused with 400, distinct from an auth failure."""
    inactive = {**active_user, "attivo": False}

    with pytest.raises(HTTPException) as exc_info:
        get_current_active_user(inactive)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_get_current_admin_user_passes_an_admin_through(active_user):
    """A user with ruolo=admin clears the admin gate."""
    admin = {**active_user, "ruolo": "admin"}

    assert get_current_admin_user(admin) is admin


def test_get_current_admin_user_rejects_a_regular_user(active_user):
    """A non-admin hitting an admin endpoint gets 403, not 401."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_admin_user(active_user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================
# Database failure paths
# ============================================
#
# The happy paths and the SQL itself live in tests/integration/test_auth.py.
# Only the "database is unreachable" branches stay here: they need an injected
# failure, which is far easier to stage with a fake than with a live server.

OUTAGE = OperationalError("SELECT 1", {}, Exception("could not connect to server"))


def test_authenticate_user_reports_a_database_outage_as_unavailable(fake_db):
    """
    An outage is 503, not "wrong credentials".

    Returning None here would tell a user their password is wrong and send the
    client back to the login form, retrying against a database already in trouble.
    """
    fake_db(auth, error=OUTAGE)

    with pytest.raises(HTTPException) as exc_info:
        authenticate_user("apicoltore@example.org", PASSWORD)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_get_current_user_reports_a_database_outage_as_unavailable(fake_db):
    """A valid token during an outage is 503, not an invalid-credentials 401."""
    fake_db(auth, error=OUTAGE)
    credentials = bearer(create_access_token({"sub": "a@b.org"}))

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_get_current_user_rejects_a_malformed_token(fake_db):
    """Garbage in the Authorization header is a 401, not a 500 — no DB needed."""
    fake_db(auth, rows=[])

    credentials = bearer("not.a.jwt")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_rejects_a_token_without_a_subject(fake_db):
    """A token carrying no `sub` claim identifies nobody, before any query runs."""
    fake_db(auth, rows=[])

    credentials = bearer(create_access_token({"role": "admin"}))

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_arnia_access_reports_a_database_outage_as_unavailable(fake_db):
    """An outage is 503, not "you lack permission on this arnia"."""
    fake_db(auth, error=OUTAGE)

    with pytest.raises(HTTPException) as exc_info:
        check_user_arnia_access(7, 99, "arnia.read")

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def outage():
    """A fresh exception each time: a reported one is marked and never sent twice."""
    return OperationalError("SELECT 1", {}, Exception("could not connect to server"))


@pytest.mark.parametrize(
    "call",
    [
        lambda: authenticate_user("apicoltore@example.org", PASSWORD),
        lambda: get_current_user(bearer(create_access_token({"sub": "a@b.org"}))),
        lambda: check_user_arnia_access(7, 99, "arnia.read"),
    ],
    ids=["login", "current user", "arnia access"],
)
def test_a_database_outage_is_reported(fake_db, reporter, call):
    """
    The 503 still goes to the client, and the outage to the maintainers (#56).

    Every authenticated request passes through here first, so without this an
    API-side outage would never be reported at all.
    """
    error = outage()
    fake_db(auth, error=error)

    with pytest.raises(HTTPException) as exc_info:
        call()

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    [(sent, _, _)] = reporter.reports
    assert sent is error


def test_an_unknown_action_is_rejected(fake_db):
    """
    Asking for an action that does not exist raises instead of granting access.

    An unknown action is listed in no role, so a lookup that merely defaulted
    would answer "owner only" — and an owner would get it without anyone
    having decided so. A typo at a call site must fail loudly instead.
    """
    session = fake_db(auth, rows=["user"])

    with pytest.raises(ValueError, match="sconosciuta"):
        check_user_arnia_access(7, 99, "arnia.superuser")

    # Rejected before touching the database.
    assert session.queries == []
