"""Queries on `utenti_arnie`, the user-to-arnia association."""

from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from meshbee_core.models import UtenteArnia

PAIR = ["id_utente", "id_arnia"]


def active(session: Session, id_utente: int, id_arnia: int) -> UtenteArnia | None:
    return session.exec(
        select(UtenteArnia).where(
            UtenteArnia.id_utente == id_utente,
            UtenteArnia.id_arnia == id_arnia,
            UtenteArnia.attivo.is_(True),
        )
    ).first()


def get_permesso(
    session: Session, id_utente: int, id_arnia: int
) -> dict[str, Any] | None:
    """The permission level of an *active* association, or None if there is none."""
    association = active(session, id_utente, id_arnia)
    return {"permessi": association.permessi} if association else None


def upsert(
    session: Session, id_utente: int, id_arnia: int, permessi: str, id_apiario: int
) -> None:
    """
    Grant access, reviving and re-levelling a previously removed association.

    `id_apiario` only places a new association: a revived one stays in the
    apiary the user had put the hive in.
    """
    statement = pg_insert(UtenteArnia).values(
        id_utente=id_utente,
        id_arnia=id_arnia,
        permessi=permessi,
        attivo=True,
        id_apiario=id_apiario,
    )
    session.exec(
        statement.on_conflict_do_update(
            index_elements=PAIR,
            set_={
                "permessi": statement.excluded.permessi,
                "attivo": True,
                "data_disassociazione": None,
            },
        )
    )


def insert_if_absent(
    session: Session, id_utente: int, id_arnia: int, permessi: str, id_apiario: int
) -> None:
    """
    Grant access only where none was ever recorded, leaving existing rows alone.

    Deliberately not `upsert`: this is for bootstrapping, which re-runs on every
    `docker-compose up`. Reviving an association an admin had revoked, on every
    restart, would be a silent authorization change.
    """
    session.exec(
        pg_insert(UtenteArnia)
        .values(
            id_utente=id_utente,
            id_arnia=id_arnia,
            permessi=permessi,
            attivo=True,
            id_apiario=id_apiario,
        )
        .on_conflict_do_nothing(index_elements=PAIR)
    )


def deactivate(
    session: Session, id_utente: int, id_arnia: int
) -> dict[str, Any] | None:
    association = active(session, id_utente, id_arnia)
    if association is None:
        return None
    association.attivo = False
    association.data_disassociazione = func.now()
    session.flush()
    return {"id": association.id}


def move(
    session: Session, id_utente: int, id_arnia: int, id_apiario: int
) -> dict[str, Any] | None:
    """Put the user's active association with an arnia in another apiary."""
    association = active(session, id_utente, id_arnia)
    if association is None:
        return None
    association.id_apiario = id_apiario
    session.flush()
    return {"id_arnia": id_arnia, "id_apiario": id_apiario}


def move_all(session: Session, from_apiario: int, to_apiario: int) -> None:
    """Re-point every association, revoked ones included, from one apiary to another."""
    session.exec(
        update(UtenteArnia)
        .where(UtenteArnia.id_apiario == from_apiario)
        .values(id_apiario=to_apiario)
    )
