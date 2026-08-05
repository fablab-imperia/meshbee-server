"""Tests for password hashing (meshbee_core/security.py)."""
import pytest

from meshbee_core.security import get_password_hash, verify_password

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def password_hash():
    """A real bcrypt hash of PASSWORD, computed once (12 rounds is deliberately slow)."""
    return get_password_hash(PASSWORD)


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

    get_password_hash stays permissive — the guard lives at the API edge, in
    schemas.validate_password_length, so nothing longer can reach it through a
    request. Pinned here so the day bcrypt starts raising instead of truncating,
    the suite says so rather than a caller discovering it in production.
    """
    long_password = "x" * 100
    hashed = get_password_hash(long_password)

    assert verify_password("x" * 72, hashed) is True
