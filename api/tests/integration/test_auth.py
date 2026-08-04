"""Authentication against a real database (api/auth.py).

These exercise the SQL itself — column names, joins, parameter order and the
CHECK constraints in database/init.sql — which the fake cursor in
tests/unit/test_auth.py cannot verify.
"""
import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

import auth
from auth import (
    authenticate_user,
    check_user_arnia_access,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
)

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def password_hash():
    """A real bcrypt hash of PASSWORD, computed once (12 rounds is deliberately slow)."""
    return get_password_hash(PASSWORD)


@pytest.fixture
def utente(use_db, make_utente, password_hash):
    """An active user that exists in the database, with auth pointed at it."""
    use_db(auth)
    return make_utente(password_hash=password_hash)


def bearer(token):
    """Wrap a raw token the way HTTPBearer hands it to the dependency."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ============================================
# authenticate_user
# ============================================


def test_authenticate_user_accepts_valid_credentials(db, utente):
    """The login query finds the user and the password verifies against the stored hash."""
    result = authenticate_user(utente["email"], PASSWORD)

    assert result is not None
    assert result["id_utente"] == utente["id_utente"]
    assert result["email"] == utente["email"]


def test_authenticate_user_stamps_ultimo_accesso(db, utente):
    """A successful login updates ultimo_accesso for that user — the UPDATE really runs."""
    assert utente["ultimo_accesso"] is None

    authenticate_user(utente["email"], PASSWORD)

    db.execute("SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (utente["id_utente"],))
    assert db.fetchone()["ultimo_accesso"] is not None


def test_authenticate_user_rejects_an_unknown_email(db, utente):
    """An email with no row returns None."""
    assert authenticate_user("nobody@example.org", PASSWORD) is None


def test_authenticate_user_rejects_a_deactivated_user(db, use_db, make_utente, password_hash):
    """attivo=false denies the login and leaves ultimo_accesso untouched."""
    use_db(auth)
    inactive = make_utente(password_hash=password_hash, attivo=False)

    assert authenticate_user(inactive["email"], PASSWORD) is None

    db.execute("SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (inactive["id_utente"],))
    assert db.fetchone()["ultimo_accesso"] is None


def test_authenticate_user_rejects_a_wrong_password(db, utente):
    """A wrong password denies the login and leaves ultimo_accesso untouched."""
    assert authenticate_user(utente["email"], "wrong-password") is None

    db.execute("SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (utente["id_utente"],))
    assert db.fetchone()["ultimo_accesso"] is None


# ============================================
# get_current_user
# ============================================


@pytest.mark.anyio
async def test_get_current_user_resolves_a_valid_access_token(db, utente):
    """The lookup query returns every column the endpoint layer expects."""
    result = await get_current_user(bearer(create_access_token({"sub": utente["email"]})))

    assert result["id_utente"] == utente["id_utente"]
    # Selected by name in auth.py: a renamed column would break these.
    assert set(result) == {
        "id_utente", "email", "nome", "cognome", "ruolo", "attivo",
        "data_creazione", "data_attivazione", "data_disattivazione", "ultimo_accesso",
    }
    # The password hash must never leave the database on this path.
    assert "password_hash" not in result


@pytest.mark.anyio
async def test_get_current_user_rejects_a_refresh_token(db, utente):
    """A refresh token must not be usable as an access token."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(bearer(create_refresh_token({"sub": utente["email"]})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_get_current_user_rejects_a_user_deactivated_since_issuing(
    db, use_db, make_utente, password_hash
):
    """A still-valid token stops working once the account is deactivated."""
    use_db(auth)
    inactive = make_utente(password_hash=password_hash, attivo=False)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(bearer(create_access_token({"sub": inactive["email"]})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_get_current_user_rejects_a_deleted_user(db, utente):
    """A token for an account that no longer exists is refused."""
    token = create_access_token({"sub": utente["email"]})
    db.execute("DELETE FROM utenti WHERE id_utente = %s", (utente["id_utente"],))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(bearer(token))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================
# check_user_arnia_access
# ============================================


def test_admin_reaches_any_arnia_without_an_association(db, use_db, make_utente, make_arnia):
    """Admins bypass utenti_arnie entirely, with no row associating them."""
    use_db(auth)
    admin = make_utente(ruolo="admin")
    arnia = make_arnia()

    assert check_user_arnia_access(admin["id_utente"], arnia["id_arnia"]) is True


def test_user_without_an_association_is_denied(db, use_db, make_utente, make_arnia):
    """No row in utenti_arnie means no access."""
    use_db(auth)
    utente = make_utente()
    arnia = make_arnia()

    assert check_user_arnia_access(utente["id_utente"], arnia["id_arnia"]) is False


def test_an_inactive_association_is_denied(db, use_db, make_utente, make_arnia, grant_access):
    """The query filters on attivo = true: a revoked association grants nothing."""
    use_db(auth)
    utente = make_utente()
    arnia = make_arnia()
    grant_access(utente["id_utente"], arnia["id_arnia"], "admin", attivo=False)

    assert check_user_arnia_access(utente["id_utente"], arnia["id_arnia"]) is False


def test_access_is_scoped_to_the_associated_arnia(db, use_db, make_utente, make_arnia, grant_access):
    """Permission on one arnia does not leak to another — the id_arnia filter works."""
    use_db(auth)
    utente = make_utente()
    granted, other = make_arnia(), make_arnia()
    grant_access(utente["id_utente"], granted["id_arnia"], "admin")

    assert check_user_arnia_access(utente["id_utente"], granted["id_arnia"]) is True
    assert check_user_arnia_access(utente["id_utente"], other["id_arnia"]) is False


@pytest.mark.parametrize(
    "granted, required, expected",
    [
        ("read", "read", True),
        ("write", "read", True),
        ("admin", "read", True),
        ("read", "write", False),
        ("write", "write", True),
        ("admin", "write", True),
        ("read", "admin", False),
        ("write", "admin", False),
        ("admin", "admin", True),
    ],
)
def test_permissions_are_hierarchical(
    db, use_db, make_utente, make_arnia, grant_access, granted, required, expected
):
    """admin > write > read: a granted level satisfies every level below it."""
    use_db(auth)
    utente = make_utente()
    arnia = make_arnia()
    grant_access(utente["id_utente"], arnia["id_arnia"], granted)

    assert check_user_arnia_access(utente["id_utente"], arnia["id_arnia"], required) is expected
