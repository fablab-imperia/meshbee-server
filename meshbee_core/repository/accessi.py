"""Queries on `utenti_arnie`, the user-to-arnia association."""
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from meshbee_core.models import UtenteArnia

PAIR = ["id_utente", "id_arnia"]


def active(session: Session, id_utente: int, id_arnia: int) -> Optional[UtenteArnia]:
    return session.exec(
        select(UtenteArnia).where(
            UtenteArnia.id_utente == id_utente,
            UtenteArnia.id_arnia == id_arnia,
            UtenteArnia.attivo.is_(True),
        )
    ).first()


def get_permesso(session: Session, id_utente: int, id_arnia: int) -> Optional[Dict[str, Any]]:
    """The permission level of an *active* association, or None if there is none."""
    association = active(session, id_utente, id_arnia)
    return {"permessi": association.permessi} if association else None


def upsert(session: Session, id_utente: int, id_arnia: int, permessi: str) -> None:
    """Grant access, reviving and re-levelling a previously removed association."""
    statement = pg_insert(UtenteArnia).values(
        id_utente=id_utente, id_arnia=id_arnia, permessi=permessi, attivo=True
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


def insert_if_absent(session: Session, id_utente: int, id_arnia: int, permessi: str) -> None:
    """
    Grant access only where none was ever recorded, leaving existing rows alone.

    Deliberately not `upsert`: this is for bootstrapping, which re-runs on every
    `docker-compose up`. Reviving an association an admin had revoked, on every
    restart, would be a silent authorization change.
    """
    session.exec(
        pg_insert(UtenteArnia)
        .values(id_utente=id_utente, id_arnia=id_arnia, permessi=permessi, attivo=True)
        .on_conflict_do_nothing(index_elements=PAIR)
    )


def deactivate(session: Session, id_utente: int, id_arnia: int) -> Optional[Dict[str, Any]]:
    association = active(session, id_utente, id_arnia)
    if association is None:
        return None
    association.attivo = False
    association.data_disassociazione = func.now()
    session.flush()
    return {"id": association.id}
