"""Authentication against a real database (api/auth.py).

These exercise the SQL itself — column names, joins, parameter order and the
CHECK constraints from meshbee_core/models.py — which the fake cursor in
tests/unit/test_auth.py cannot verify.
"""

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from api import auth
from api.auth import (
    authenticate_user,
    check_user_apiario_access,
    check_user_arnia_access,
    create_access_token,
    create_refresh_token,
    get_current_user,
)


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


def test_authenticate_user_accepts_valid_credentials(db, utente, known_password):
    """The login query finds the user and the password verifies against the stored hash."""
    result = authenticate_user(utente["email"], known_password)

    assert result is not None
    assert result["id_utente"] == utente["id_utente"]
    assert result["email"] == utente["email"]


def test_authenticate_user_stamps_ultimo_accesso(db, utente, known_password):
    """A successful login updates ultimo_accesso for that user — the UPDATE really runs."""
    assert utente["ultimo_accesso"] is None

    authenticate_user(utente["email"], known_password)

    db.execute(
        "SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (utente["id_utente"],)
    )
    assert db.fetchone()["ultimo_accesso"] is not None


def test_authenticate_user_rejects_an_unknown_email(db, utente, known_password):
    """An email with no row returns None."""
    assert authenticate_user("nobody@example.org", known_password) is None


def test_authenticate_user_rejects_a_deactivated_user(
    db, use_db, make_utente, password_hash, known_password
):
    """attivo=false denies the login and leaves ultimo_accesso untouched."""
    use_db(auth)
    inactive = make_utente(password_hash=password_hash, attivo=False)

    assert authenticate_user(inactive["email"], known_password) is None

    db.execute(
        "SELECT ultimo_accesso FROM utenti WHERE id_utente = %s",
        (inactive["id_utente"],),
    )
    assert db.fetchone()["ultimo_accesso"] is None


def test_authenticate_user_rejects_a_wrong_password(db, utente):
    """A wrong password denies the login and leaves ultimo_accesso untouched."""
    assert authenticate_user(utente["email"], "wrong-password") is None

    db.execute(
        "SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (utente["id_utente"],)
    )
    assert db.fetchone()["ultimo_accesso"] is None


# ============================================
# get_current_user
# ============================================


def test_get_current_user_resolves_a_valid_access_token(db, utente):
    """The lookup query returns every column the endpoint layer expects."""
    result = get_current_user(bearer(create_access_token({"sub": utente["email"]})))

    assert result["id_utente"] == utente["id_utente"]
    # Selected by name in auth.py: a renamed column would break these.
    assert set(result) == {
        "id_utente",
        "email",
        "nome",
        "cognome",
        "ruolo",
        "attivo",
        "data_creazione",
        "data_attivazione",
        "data_disattivazione",
        "ultimo_accesso",
    }
    # The password hash must never leave the database on this path.
    assert "password_hash" not in result


def test_get_current_user_rejects_a_refresh_token(db, utente):
    """A refresh token must not be usable as an access token."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer(create_refresh_token({"sub": utente["email"]})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_rejects_a_user_deactivated_since_issuing(
    db, use_db, make_utente, password_hash
):
    """A still-valid token stops working once the account is deactivated."""
    use_db(auth)
    inactive = make_utente(password_hash=password_hash, attivo=False)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer(create_access_token({"sub": inactive["email"]})))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_rejects_a_deleted_user(db, utente):
    """A token for an account that no longer exists is refused."""
    token = create_access_token({"sub": utente["email"]})
    db.execute("DELETE FROM utenti WHERE id_utente = %s", (utente["id_utente"],))

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(bearer(token))

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================
# check_user_arnia_access / check_user_apiario_access
# ============================================

# What each access allows, the whole table. Owner-only actions are those no
# role lists; see ROLE_ACTIONS in meshbee_core/services/auth.py.
ACCESS_MATRIX = {
    "arnia.read": {"viewer", "collaborator", "manager", "owner"},
    "apiario.read": {"viewer", "collaborator", "manager", "owner"},
    "attivita.write": {"collaborator", "manager", "owner"},
    "arnia.update": {"manager", "owner"},
    "apiario.update": {"manager", "owner"},
    "arnia.retire": {"owner"},
    "arnia.move": {"owner"},
    "apiario.delete": {"owner"},
    "apiario.share": {"owner"},
}
ACCESSES = ["viewer", "collaborator", "manager", "owner"]


def test_the_matrix_covers_every_action():
    """A new action must be placed in the table above, or it goes untested."""
    from meshbee_core.services.auth import ACTIONS

    assert set(ACCESS_MATRIX) == ACTIONS


@pytest.mark.parametrize("action", sorted(ACCESS_MATRIX))
@pytest.mark.parametrize("accesso", ACCESSES)
def test_each_access_allows_exactly_its_actions(
    db, use_db, utente_con_arnia, accesso, action
):
    """The same answer on the hive and on its apiary, for every pair."""
    use_db(auth)
    utente, arnia = utente_con_arnia(accesso)
    expected = accesso in ACCESS_MATRIX[action]

    assert (
        check_user_arnia_access(utente["id_utente"], arnia["id_arnia"], action)
        is expected
    )
    assert (
        check_user_apiario_access(utente["id_utente"], arnia["id_apiario"], action)
        is expected
    )


@pytest.mark.parametrize("action", sorted(ACCESS_MATRIX))
def test_admin_may_do_everything_without_owning_or_a_share(
    db, use_db, make_utente, make_arnia, action
):
    """Even on an unassigned hive, which nobody else can reach."""
    use_db(auth)
    admin = make_utente(ruolo="admin")
    arnia = make_arnia()

    assert (
        check_user_arnia_access(admin["id_utente"], arnia["id_arnia"], action) is True
    )


def test_a_user_with_neither_ownership_nor_a_share_is_denied(
    db, use_db, make_utente, make_arnia
):
    use_db(auth)
    utente, owner = make_utente(), make_utente()
    arnia = make_arnia(apiario=owner)

    assert (
        check_user_arnia_access(utente["id_utente"], arnia["id_arnia"], "arnia.read")
        is False
    )
    assert (
        check_user_apiario_access(
            utente["id_utente"], arnia["id_apiario"], "apiario.read"
        )
        is False
    )


def test_an_unassigned_hive_is_reachable_only_by_admins(
    db, use_db, make_utente, make_arnia
):
    use_db(auth)
    arnia = make_arnia()

    assert (
        check_user_arnia_access(
            make_utente()["id_utente"], arnia["id_arnia"], "arnia.read"
        )
        is False
    )


def test_a_share_is_scoped_to_its_apiary(
    db, use_db, make_utente, make_apiario, make_arnia, share
):
    """Sharing one of an owner's apiaries opens nothing in the others."""
    use_db(auth)
    utente, owner = make_utente(), make_utente()
    shared = make_apiario(owner)
    inside = make_arnia(apiario=shared)
    outside = make_arnia(apiario=owner)
    share(utente["id_utente"], shared["id_apiario"], "manager")

    assert (
        check_user_arnia_access(utente["id_utente"], inside["id_arnia"], "arnia.read")
        is True
    )
    assert (
        check_user_arnia_access(utente["id_utente"], outside["id_arnia"], "arnia.read")
        is False
    )
