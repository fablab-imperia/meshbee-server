"""Authentication, and authorization on apiaries and their hives.

Token handling is *not* here: a JWT is an HTTP transport concern and lives in
the API entry point. What lives here is who a password belongs to and what a
user is allowed to do with an arnia — the MQTT handler does not need it today,
but neither is it an HTTP concept.
"""

from typing import Any

from meshbee_core.repository import accessi, utenti
from meshbee_core.repository.accessi import OWNER
from meshbee_core.security import verify_password

# What each role shared on an apiary allows, on the apiary and its hives. The
# owner may do everything, so any action listed in no role is owner-only.
# Keys must match the RuoloApiario literal, and therefore the CHECK constraint
# on utenti_apiari.ruolo — tests/integration/core/test_schemas.py asserts it.
_VIEWER = {"apiario.read", "arnia.read"}
_COLLABORATOR = _VIEWER | {"attivita.write"}
_MANAGER = _COLLABORATOR | {"apiario.update", "arnia.update"}
ROLE_ACTIONS = {
    "viewer": _VIEWER,
    "collaborator": _COLLABORATOR,
    "manager": _MANAGER,
}
OWNER_ONLY = {"apiario.delete", "apiario.share", "arnia.move", "arnia.retire"}
ACTIONS = _MANAGER | OWNER_ONLY


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


def allows(accesso: str | None, action: str) -> bool:
    """
    Whether an access ("owner", a shared role, or None) allows an action.

    Raises:
        ValueError: if the action is unknown.
    """
    # Fail closed and loudly on an unknown action: a typo must never read as
    # "nobody listed it, so everybody may".
    if action not in ACTIONS:
        raise ValueError(f"Azione sconosciuta: {action!r}")
    if accesso == OWNER:
        return True
    return action in ROLE_ACTIONS.get(accesso, ())


def is_admin(session, id_utente: int) -> bool:
    user = utenti.get_ruolo(session, id_utente)
    return bool(user and user["ruolo"] == "admin")


def can_on_arnia(session, id_utente: int, id_arnia: int, action: str) -> bool:
    """
    Whether a user may perform an action on a hive, through its apiary.

    An admin may do everything; an unassigned hive is reachable only by admins.

    Raises:
        ValueError: if the action is unknown.
    """
    if action not in ACTIONS:
        raise ValueError(f"Azione sconosciuta: {action!r}")
    if is_admin(session, id_utente):
        return True
    return allows(accessi.accesso_su_arnia(session, id_utente, id_arnia), action)


def can_on_apiario(session, id_utente: int, id_apiario: int, action: str) -> bool:
    """
    Whether a user may perform an action on an apiary. An admin may do everything.

    Raises:
        ValueError: if the action is unknown.
    """
    if action not in ACTIONS:
        raise ValueError(f"Azione sconosciuta: {action!r}")
    if is_admin(session, id_utente):
        return True
    return allows(accessi.accesso_su_apiario(session, id_utente, id_apiario), action)
