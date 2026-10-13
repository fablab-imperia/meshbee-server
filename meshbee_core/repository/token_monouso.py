"""Queries on `token_monouso`: single-use tokens sent by email (#54, #55).

Rows are found by the token's SHA-256 (`security.hash_token`), never by the token
itself, which is not stored. Times are compared against the database clock
(`func.now()`), the same clock that stamps `data_creazione`.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import func
from sqlalchemy import update as sql_update
from sqlmodel import Session, select

from meshbee_core.limits import ScopoToken
from meshbee_core.models import TokenMonouso
from meshbee_core.repository import as_dict


def insert(
    session: Session,
    scopo: ScopoToken,
    token_hash: str,
    lifetime: timedelta,
    email: str,
    id_utente: int | None = None,
    id_mittente: int | None = None,
) -> dict[str, Any]:
    row = TokenMonouso(
        scopo=scopo,
        token_hash=token_hash,
        data_scadenza=func.now() + lifetime,
        email=email,
        id_utente=id_utente,
        id_mittente=id_mittente,
    )
    session.add(row)
    session.flush()
    return as_dict(row)


def count_since(
    session: Session, id_utente: int, scopo: ScopoToken, window: timedelta
) -> int:
    """How many tokens of this purpose the user was issued within `window`, spent or not."""
    return session.exec(
        select(func.count()).where(
            TokenMonouso.id_utente == id_utente,
            TokenMonouso.scopo == scopo,
            TokenMonouso.data_creazione > func.now() - window,
        )
    ).one()


def spend(
    session: Session, scopo: ScopoToken, token_hash: str
) -> dict[str, Any] | None:
    """
    Spend a live token; return whom it is for, or None if it is unknown, expired or spent.

    The result carries `id_utente`, `email` and `id_mittente`.

    A single conditional UPDATE, so two concurrent uses of one token cannot both
    win: the second waits on the row lock, re-checks `data_utilizzo` and
    updates nothing.
    """
    row = session.exec(
        sql_update(TokenMonouso)
        .where(
            TokenMonouso.token_hash == token_hash,
            TokenMonouso.scopo == scopo,
            TokenMonouso.data_utilizzo.is_(None),
            TokenMonouso.data_scadenza > func.now(),
        )
        .values(data_utilizzo=func.now())
        .returning(TokenMonouso.id_utente, TokenMonouso.email, TokenMonouso.id_mittente)
    ).first()
    return dict(row._mapping) if row is not None else None


def spend_all(session: Session, id_utente: int, scopo: ScopoToken) -> int:
    """Spend every unspent token of this purpose the user holds; returns how many."""
    result = session.exec(
        sql_update(TokenMonouso)
        .where(
            TokenMonouso.id_utente == id_utente,
            TokenMonouso.scopo == scopo,
            TokenMonouso.data_utilizzo.is_(None),
        )
        .values(data_utilizzo=func.now())
    )
    return result.rowcount


def delete_expired_before(session: Session, age: timedelta) -> None:
    """Drop every token, of any user or purpose, that expired more than `age` ago."""
    session.exec(
        sql_delete(TokenMonouso).where(TokenMonouso.data_scadenza <= func.now() - age)
    )
