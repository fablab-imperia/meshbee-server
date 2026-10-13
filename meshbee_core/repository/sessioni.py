"""Queries on `token_sessione`: one row per issued refresh token.

Rows are found by the token's SHA-256 (`security.hash_token`), never by the token
itself, which is not stored. Expiry is compared against the database clock
(`func.now()`), the same clock that stamps `data_creazione`.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import func
from sqlalchemy import update as sql_update
from sqlmodel import Session, select

from meshbee_core.models import TokenSessione
from meshbee_core.repository import as_dict


def insert(
    session: Session,
    id_utente: int,
    token_hash: str,
    lifetime_days: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    row = TokenSessione(
        id_utente=id_utente,
        refresh_token=token_hash,
        data_scadenza=func.now() + timedelta(days=lifetime_days),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(row)
    session.flush()
    return as_dict(row)


def get_by_hash(session: Session, token_hash: str) -> dict[str, Any] | None:
    """The session row, with `scaduto` telling whether it is past its expiry."""
    found = session.exec(
        select(TokenSessione, TokenSessione.data_scadenza <= func.now()).where(
            TokenSessione.refresh_token == token_hash
        )
    ).first()
    if found is None:
        return None
    row, scaduto = found
    return {**as_dict(row), "scaduto": scaduto}


def revoke(session: Session, id_token: int) -> bool:
    """
    Revoke one session; True only if this call is the one that revoked it.

    A single conditional UPDATE, so two concurrent redeems of the same token
    cannot both win: the second waits on the row lock, re-checks `revocato`
    and updates nothing.
    """
    result = session.exec(
        sql_update(TokenSessione)
        .where(
            TokenSessione.id_token == id_token,
            TokenSessione.revocato.is_not(True),
        )
        .values(revocato=True)
    )
    return result.rowcount == 1


def revoke_all(session: Session, id_utente: int) -> int:
    """Revoke every live session of a user; returns how many were revoked."""
    result = session.exec(
        sql_update(TokenSessione)
        .where(
            TokenSessione.id_utente == id_utente,
            TokenSessione.revocato.is_not(True),
        )
        .values(revocato=True)
    )
    return result.rowcount


def delete_expired(session: Session, id_utente: int) -> None:
    """
    Drop a user's expired sessions.

    Revoked rows that have not expired yet are kept: they are what detects the
    reuse of a stolen refresh token.
    """
    session.exec(
        sql_delete(TokenSessione).where(
            TokenSessione.id_utente == id_utente,
            TokenSessione.data_scadenza <= func.now(),
        )
    )
