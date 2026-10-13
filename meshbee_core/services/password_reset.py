"""Self-service password reset by email (#54).

Two steps. `request_reset` issues a single-use token for an active account and
hands it back so the caller can email it; `reset_password` spends that token
and sets the new password. Sending the email is the caller's job: this module
decides who may reset, and when, and never touches SMTP.

Only the token's SHA-256 is stored (`token_monouso`), so a copy of the database
cannot be turned into resets.
"""

import logging
from datetime import timedelta
from typing import Any

from meshbee_core.errors import InvalidData
from meshbee_core.repository import token_monouso, utenti
from meshbee_core.security import get_password_hash, hash_token, new_token
from meshbee_core.services import auth

logger = logging.getLogger(__name__)

SCOPO = "password_reset"

# The per-account cap counts requests over this window.
RATE_WINDOW = timedelta(hours=1)

# How long a row is kept after it expires. A reset token lives at most a day,
# so by then it is also out of the cap's window and of no further use.
RETENTION = timedelta(days=1)

# One answer for an unknown, expired or spent token, and for an account that has
# been deactivated since: which one it was is of no use to the person holding it.
INVALID_LINK = "Link non valido o scaduto: richiedine uno nuovo"


def request_reset(
    session, email: str, lifetime: timedelta, max_per_window: int
) -> tuple[dict[str, Any], str] | None:
    """
    Issue a reset token for `email`: return (user, token), or None if nothing is to be sent.

    None for an unknown or deactivated account, and for one that has already
    had `max_per_window` tokens within `RATE_WINDOW`. The caller must answer
    the same in every case, so the response does not tell which addresses are
    registered. A new token spends the user's earlier unused ones.
    """
    user = utenti.get_by_email(session, email)
    if user is None or not user["attivo"]:
        return None

    id_utente = user["id_utente"]
    token_monouso.delete_expired_before(session, RETENTION)
    if (
        token_monouso.count_since(session, id_utente, SCOPO, RATE_WINDOW)
        >= max_per_window
    ):
        logger.info(f"Password reset for user {id_utente} skipped: too many requests")
        return None

    token_monouso.spend_all(session, id_utente, SCOPO)
    token = new_token()
    token_monouso.insert(
        session,
        SCOPO,
        hash_token(token),
        lifetime,
        email=user["email"],
        id_utente=id_utente,
    )
    return user, token


def reset_password(session, token: str, new_password: str) -> dict[str, Any]:
    """
    Spend a reset token and set the new password; return the user it belonged to.

    Every other reset token of the user is spent too, and every refresh token
    revoked: a new password logs out every device that knew the old one.
    Access tokens already issued stay valid until they expire.

    Raises:
        InvalidData: if the token is unknown, expired or spent, or the account
            has been deactivated.
    """
    spent = token_monouso.spend(session, SCOPO, hash_token(token))
    user = utenti.get_by_id(session, spent["id_utente"]) if spent else None
    if user is None or not user["attivo"]:
        raise InvalidData(INVALID_LINK)

    id_utente = user["id_utente"]
    utenti.set_password_hash(session, id_utente, get_password_hash(new_password))
    token_monouso.spend_all(session, id_utente, SCOPO)
    auth.revoke_sessions(session, id_utente)
    return user
