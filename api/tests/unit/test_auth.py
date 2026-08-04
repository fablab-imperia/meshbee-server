"""Tests for authentication and JWT handling (api/auth.py)."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt

import auth
from auth import (
    authenticate_user,
    check_user_arnia_access,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    get_current_admin_user,
    get_current_user,
    get_password_hash,
    verify_password,
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
# Password hashing
# ============================================


def test_password_hash_verifies_against_the_original(password_hash):
    """The hash produced by get_password_hash is accepted by verify_password."""
    assert verify_password(PASSWORD, password_hash) is True


def test_verify_password_rejects_a_wrong_password(password_hash):
    """A password that does not match the hash is refused."""
    assert verify_password("wrong-password", password_hash) is False


def test_password_hash_is_salted():
    """Two hashes of the same password differ: a stolen table cannot be rainbow-matched."""
    first = get_password_hash(PASSWORD)
    second = get_password_hash(PASSWORD)

    assert first != second
    assert verify_password(PASSWORD, first) and verify_password(PASSWORD, second)


def test_verify_password_returns_false_on_a_corrupt_hash():
    """A malformed password_hash column must deny the login, not raise a 500."""
    assert verify_password(PASSWORD, "not-a-bcrypt-hash") is False


def test_passwords_are_truncated_at_72_bytes(password_hash):
    """
    Documented bcrypt exposure: only the first 72 bytes are hashed.

    A user with a longer password can authenticate with just its 72-byte prefix.
    Pinned here so the day bcrypt starts raising instead of truncating, the
    suite says so rather than the login endpoint returning 500.
    """
    long_password = "x" * 100
    hashed = get_password_hash(long_password)

    assert verify_password("x" * 72, hashed) is True


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


def test_authenticate_user_returns_none_when_the_database_fails(fake_db):
    """A database outage denies the login instead of surfacing the exception."""
    fake_db(auth, error=RuntimeError("connection refused"))

    assert authenticate_user("apicoltore@example.org", PASSWORD) is None


@pytest.mark.anyio
async def test_get_current_user_rejects_a_malformed_token(fake_db):
    """Garbage in the Authorization header is a 401, not a 500 — no DB needed."""
    fake_db(auth, rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(bearer("not.a.jwt"))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_get_current_user_rejects_a_token_without_a_subject(fake_db):
    """A token carrying no `sub` claim identifies nobody, before any query runs."""
    fake_db(auth, rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(bearer(create_access_token({"role": "admin"})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_arnia_access_is_denied_when_the_database_fails(fake_db):
    """A database outage denies access rather than surfacing the exception."""
    fake_db(auth, error=RuntimeError("connection refused"))

    assert check_user_arnia_access(7, 99) is False


def test_an_unknown_permission_value_denies_access(fake_db):
    """
    An unrecognised permessi value ranks below read instead of granting access.

    Defensive: init.sql constrains permessi to read/write/admin, so this state is
    unreachable through the schema and can only be reproduced with a fake.
    """
    fake_db(auth, rows=[{"ruolo": "user"}, {"permessi": "superuser"}])

    assert check_user_arnia_access(7, 99, "read") is False
