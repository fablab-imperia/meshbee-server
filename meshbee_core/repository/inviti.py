"""Queries on `inviti_apiari`: apiaries shared with emails that have no account yet (#40)."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, delete, select

from meshbee_core.models import InvitoApiario
from meshbee_core.repository import as_dict

# Every column, for RETURNING: rows come back as plain mappings, not ORM objects.
COLUMNS = tuple(InvitoApiario.__table__.c)


def upsert(session: Session, email: str, id_apiario: int, ruolo: str) -> dict[str, Any]:
    """Invite the email to the apiary, or change the role of its pending invitation."""
    statement = pg_insert(InvitoApiario).values(
        email=email, id_apiario=id_apiario, ruolo=ruolo
    )
    row = session.exec(
        statement.on_conflict_do_update(
            index_elements=["email", "id_apiario"],
            set_={"ruolo": statement.excluded.ruolo},
        ).returning(*COLUMNS)
    ).one()
    return dict(row._mapping)


def get(session: Session, id_invito: int, id_apiario: int) -> dict[str, Any] | None:
    return as_dict(_find(session, id_invito, id_apiario))


def update_ruolo(
    session: Session, id_invito: int, id_apiario: int, ruolo: str
) -> dict[str, Any] | None:
    invito = _find(session, id_invito, id_apiario)
    if invito is None:
        return None
    invito.ruolo = ruolo
    session.flush()
    return as_dict(invito)


def delete_one(
    session: Session, id_invito: int, id_apiario: int
) -> dict[str, Any] | None:
    """Delete one invitation; return the row it was, or None if there was none."""
    row = session.exec(
        delete(InvitoApiario)
        .where(
            InvitoApiario.id_invito == id_invito,
            InvitoApiario.id_apiario == id_apiario,
        )
        .returning(*COLUMNS)
    ).first()
    return dict(row._mapping) if row is not None else None


def take_for_email(session: Session, email: str) -> list[dict[str, Any]]:
    """Delete every invitation to `email` and return them, to be turned into shares."""
    rows = session.exec(
        delete(InvitoApiario)
        .where(InvitoApiario.email == email)
        .returning(InvitoApiario.id_apiario, InvitoApiario.ruolo)
    ).all()
    return [dict(row._mapping) for row in rows]


def _find(session: Session, id_invito: int, id_apiario: int) -> InvitoApiario | None:
    return session.exec(
        select(InvitoApiario).where(
            InvitoApiario.id_invito == id_invito,
            InvitoApiario.id_apiario == id_apiario,
        )
    ).first()


def exists_for_email(session: Session, email: str) -> bool:
    """Whether any apiary still has a pending invitation to `email`."""
    return (
        session.exec(
            select(InvitoApiario.id_invito).where(InvitoApiario.email == email).limit(1)
        ).first()
        is not None
    )
