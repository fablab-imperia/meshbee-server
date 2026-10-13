"""Apiary invitations by email (#55), on top of pending invitations (#40).

Sharing with an email that has no account stores a pending invitation
(`services/accessi.py`). With email on, the invited person is also sent a
single-use link (`token_monouso`, `scopo = invite`) to create their account,
which accepts every invitation to that email at once.

Like `password_reset`, this module decides and hands tokens back; sending the
email is the caller's job. Only the token's SHA-256 is stored.
"""

import logging
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.models import UserCreate
from meshbee_core.repository import inviti, token_monouso, utenti
from meshbee_core.security import hash_token, new_token
from meshbee_core.services import accessi
from meshbee_core.services import utenti as utenti_service
from meshbee_core.services.password_reset import RETENTION

logger = logging.getLogger(__name__)

SCOPO = "invite"

# The per-sender cap counts invitation emails over this window.
CAP_WINDOW = timedelta(days=1)

# One answer for an unknown, expired, used or withdrawn invitation, and for an
# address that has meanwhile got an account.
INVALID_LINK = (
    "Invito non valido o scaduto: chiedi a chi ti ha invitato di inviarlo di nuovo"
)


def share(
    session,
    id_apiario: int,
    condivisione,
    id_mittente: int,
    invite_lifetime: timedelta | None,
    max_per_day: int,
) -> dict[str, Any]:
    """
    Share the apiary (`accessi.share`), and issue an invitation token if it is pending.

    `invite_lifetime` None means no email can be sent, so no token is issued.
    The result is `accessi.share`'s, plus `token`: the invitation to email, or
    None when there is none to send (an existing account, email off, or the
    sender's daily cap reached).
    """
    result = accessi.share(session, id_apiario, condivisione)
    token = None
    if result["stato"] == accessi.IN_ATTESA and invite_lifetime is not None:
        token = _issue(
            session, result["email"], id_mittente, invite_lifetime, max_per_day
        )
    return {**result, "token": token}


def resend(
    session,
    id_apiario: int,
    id_invito: int,
    id_mittente: int,
    invite_lifetime: timedelta,
    max_per_day: int,
) -> dict[str, Any] | None:
    """
    Issue a new invitation token for a pending invitation; the old link stops working.

    Returns the invitation with `nome_apiario` and `token`, or None if the
    sender's daily cap is reached.

    Raises:
        NotFound: if the apiary has no such pending invitation.
    """
    invito = inviti.get(session, id_invito, id_apiario)
    if invito is None:
        raise NotFound(accessi.INVITO_NOT_FOUND)
    token = _issue(session, invito["email"], id_mittente, invite_lifetime, max_per_day)
    if token is None:
        return None
    apiario = accessi.require_apiario(session, id_apiario)
    return {**invito, "nome_apiario": apiario["nome_apiario"], "token": token}


def accept(
    session, token: str, nome: str, cognome: str, password: str
) -> dict[str, Any]:
    """
    Spend an invitation token and create the account for the invited email.

    Creating it turns every pending invitation to that email into a share
    (`utenti.create_utente`). Returns the new user, role `user`.

    Raises:
        InvalidData: if the token is unknown, expired, used or withdrawn, or the
            email has an account already. A malformed invited address, which
            no account could have, is the same error.
    """
    spent = token_monouso.spend(session, SCOPO, hash_token(token))
    if spent is None or utenti.find_id_by_email(session, spent["email"]):
        raise InvalidData(INVALID_LINK)
    try:
        user = UserCreate(
            email=spent["email"], nome=nome, cognome=cognome, password=password
        )
    except ValidationError:
        raise InvalidData(INVALID_LINK) from None
    created = utenti_service.create_utente(session, user)
    token_monouso.spend_all_for_email(session, spent["email"], SCOPO)
    return created


def _issue(
    session, email: str, id_mittente: int, lifetime: timedelta, max_per_day: int
) -> str | None:
    """A new invitation token to `email`, replacing earlier ones; None past the sender's cap."""
    token_monouso.delete_expired_before(session, RETENTION)
    sent = token_monouso.count_by_sender_since(session, id_mittente, SCOPO, CAP_WINDOW)
    if sent >= max_per_day:
        logger.info(f"Invitation by user {id_mittente} not sent: daily cap reached")
        return None
    token_monouso.spend_all_for_email(session, email, SCOPO)
    token = new_token()
    token_monouso.insert(
        session,
        SCOPO,
        hash_token(token),
        lifetime,
        email=email,
        id_mittente=id_mittente,
    )
    return token
