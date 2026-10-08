"""Authentication and arnia-level authorization.

Token handling is *not* here: a JWT is an HTTP transport concern and lives in
the API entry point. What lives here is who a password belongs to and what a
user is allowed to do with an arnia — the MQTT handler does not need it today,
but neither is it an HTTP concept.
"""

from typing import Any

from meshbee_core.repository import accessi, apiari, utenti
from meshbee_core.security import verify_password

# Livelli di permesso (admin > write > read).
# Keys must match the Permesso literal, and therefore the CHECK constraint on
# utenti_arnie.permessi — tests/integration/core/test_schemas.py asserts it.
PERMISSION_LEVELS = {"read": 1, "write": 2, "admin": 3}


def authenticate(session, email: str, password: str) -> dict[str, Any] | None:
    """
    Return the user row on a successful login, None otherwise.

    Deliberately one answer for every kind of failure — unknown email, wrong
    password, deactivated account — so a caller cannot use the response to
    discover which addresses are registered.
    """
    user = utenti.get_credentials_by_email(session, email)

    if not user:
        return None

    if not user["attivo"]:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    utenti.touch_ultimo_accesso(session, user["id_utente"])

    return user


def get_utente_by_email(session, email: str) -> dict[str, Any] | None:
    """The profile behind a validated token, or None if it is gone or disabled."""
    user = utenti.get_by_email(session, email)

    if user is None or not user["attivo"]:
        return None

    return dict(user)


def has_arnia_access(
    session, id_utente: int, id_arnia: int, required_permission: str = "read"
) -> bool:
    """
    Whether a user may act on an arnia at the given level.

    Raises:
        ValueError: Se required_permission non è un permesso conosciuto
    """
    # Fail closed and loudly on an unknown requirement. Defaulting it to level 0
    # would make `user_level >= 0` true for everyone, silently granting access.
    if required_permission not in PERMISSION_LEVELS:
        raise ValueError(f"Permesso richiesto sconosciuto: {required_permission!r}")

    # Un admin ha accesso a tutte le arnie, associazione o meno.
    user = utenti.get_ruolo(session, id_utente)
    if user and user["ruolo"] == "admin":
        return True

    result = accessi.get_permesso(session, id_utente, id_arnia)
    if not result:
        return False

    # `permessi` is constrained by a CHECK (built from limits.PERMESSI) to exactly these keys,
    # so index directly instead of masking an unexpected value.
    return (
        PERMISSION_LEVELS[result["permessi"]] >= PERMISSION_LEVELS[required_permission]
    )


def has_apiario_access(session, id_utente: int, id_apiario: int) -> bool:
    """
    Whether a user may read an apiary: an admin always, anyone else through a
    hive in it they are associated with. There is no per-apiary grant.
    """
    user = utenti.get_ruolo(session, id_utente)
    if user and user["ruolo"] == "admin":
        return True
    return apiari.is_visible_to(session, id_utente, id_apiario)
