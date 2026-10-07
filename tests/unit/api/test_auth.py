"""Tests for authentication and JWT handling (api/auth.py)."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt

from api import auth
from meshbee_core.security import get_password_hash
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


def test_access_token_honours_an_explicit_lifetime():
    """An explicit expires_delta wins over the configured default."""
    payload = decode_token(create_access_token({"sub": "a@b.org"}, timedelta(minutes=15)))

    expected = datetime.utcnow() + timedelta(minutes=15)
    assert abs((datetime.utcfromtimestamp(payload["exp"]) - expected).total_seconds()) < 5


def test_access_token_defaults_to_the_configured_lifetime(monkeypatch):
    """Without expires_delta the token lives for ACCESS_TOKEN_EXPIRE_MINUTES."""
    monkeypatch.setattr(auth.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 90)

    payload = decode_token(create_access_token({"sub": "a@b.org"}))

    expected = datetime.utcnow() + timedelta(minutes=90)
    assert abs((datetime.utcfromtimestamp(payload["exp"]) - expected).total_seconds()) < 5


def test_refresh_token_uses_the_configured_lifetime(monkeypatch):
    """Refresh tokens are measured in days, from REFRESH_TOKEN_EXPIRE_DAYS."""
    monkeypatch.setattr(auth.settings, "REFRESH_TOKEN_EXPIRE_DAYS", 3)

    payload = decode_token(create_refresh_token({"sub": "a@b.org"}))

    expected = datetime.utcnow() + timedelta(days=3)
    assert abs((datetime.utcfromtimestamp(payload["exp"]) - expected).total_seconds()) < 5


def test_decode_token_rejects_an_expired_token():
    """An expired token is refused rather than silently accepted."""
    expired = create_access_token({"sub": "a@b.org"}, timedelta(minutes=-1))

    with pytest.raises(JWTError):
        decode_token(expired)


def test_decode_token_rejects_a_token_signed_with_another_key():
    """A token forged with a different secret does not validate against ours."""
    forged = jwt.encode({"sub": "a@b.org", "type": "access"}, "another-secret", algorithm="HS256")

    with pytest.raises(JWTError):
        decode_token(forged)


# ============================================
# Role dependencies
# ============================================


@pytest.mark.anyio
async def test_get_current_active_user_passes_an_active_user_through(active_user):
    """An active user is returned unchanged."""
    assert await get_current_active_user(active_user) is active_user


@pytest.mark.anyio
async def test_get_current_active_user_rejects_an_inactive_user(active_user):
    """An inactive user is refused with 400, distinct from an auth failure."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_active_user({**active_user, "attivo": False})

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.anyio
async def test_get_current_admin_user_passes_an_admin_through(active_user):
    """A user with ruolo=admin clears the admin gate."""
    admin = {**active_user, "ruolo": "admin"}

    assert await get_current_admin_user(admin) is admin


@pytest.mark.anyio
async def test_get_current_admin_user_rejects_a_regular_user(active_user):
    """A non-admin hitting an admin endpoint gets 403, not 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin_user(active_user)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================
# Database failure paths
# ============================================
#
# The happy paths and the SQL itself live in tests/integration/test_auth.py.
# Only the "database is unreachable" branches stay here: they need an injected
# failure, which is far easier to stage with a fake than with a live server.

OUTAGE = OperationalError(
    "SELECT 1", {}, Exception("could not connect to server")
)


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

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer(create_access_token({"sub": "a@b.org"})))

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_get_current_user_rejects_a_malformed_token(fake_db):
    """Garbage in the Authorization header is a 401, not a 500 — no DB needed."""
    fake_db(auth, rows=[])

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer("not.a.jwt"))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_rejects_a_token_without_a_subject(fake_db):
    """A token carrying no `sub` claim identifies nobody, before any query runs."""
    fake_db(auth, rows=[])

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer(create_access_token({"role": "admin"})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_arnia_access_reports_a_database_outage_as_unavailable(fake_db):
    """An outage is 503, not "you lack permission on this arnia"."""
    fake_db(auth, error=OUTAGE)

    with pytest.raises(HTTPException) as exc_info:
        check_user_arnia_access(7, 99)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_an_unknown_required_permission_is_rejected(fake_db):
    """
    Asking for a permission that does not exist raises instead of granting access.

    The previous `.get(required_permission, 0)` made the comparison
    `user_level >= 0`, which is true for everyone — a typo at a call site would
    have quietly opened the arnia to any associated user.
    """
    session = fake_db(auth, rows=["user", {"permessi": "read"}])

    with pytest.raises(ValueError, match="sconosciuto"):
        check_user_arnia_access(7, 99, "superuser")

    # Rejected before touching the database.
    assert session.queries == []
