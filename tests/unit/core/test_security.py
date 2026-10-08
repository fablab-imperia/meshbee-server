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


def test_a_password_over_72_bytes_is_refused_not_truncated():
    """
    bcrypt only hashes the first 72 bytes; since bcrypt 5 it raises instead.

    The guard for users lives at the API edge, in
    models.validate_password_length, so nothing longer reaches this through a
    request. Pinned here so a bcrypt that goes back to truncating silently is
    noticed by the suite rather than in production.
    """
    with pytest.raises(ValueError):
        get_password_hash("x" * 100)


def test_verify_password_denies_a_password_over_72_bytes(password_hash):
    """A login with an over-long password is a 401, not a 500."""
    assert verify_password(PASSWORD + "x" * 100, password_hash) is False
