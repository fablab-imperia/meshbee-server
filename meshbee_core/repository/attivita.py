"""Queries on `log_attivita`."""

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from meshbee_core.models import LogAttivita
from meshbee_core.paging import Page, Paging
from meshbee_core.repository import as_dict, fetch_page

# Columns `update` will accept.
UPDATABLE = ("timestamp", "tipo_attivita", "descrizione", "dati")


# Newest first; the id breaks ties between entries with the same timestamp.
NEWEST_FIRST = (LogAttivita.timestamp.desc(), LogAttivita.id_log.desc())


def list_by_arnia(
    session: Session,
    id_arnia: int,
    data_inizio,
    data_fine,
    paging: Paging,
    tipo_attivita: str | None = None,
) -> Page:
    query = select(LogAttivita).where(
        LogAttivita.id_arnia == id_arnia,
        LogAttivita.timestamp >= data_inizio,
        LogAttivita.timestamp <= data_fine,
    )
    if tipo_attivita:
        query = query.where(LogAttivita.tipo_attivita == tipo_attivita)

    return fetch_page(session, query.order_by(*NEWEST_FIRST), paging)


def list_all(session: Session, paging: Paging) -> Page:
    return fetch_page(session, select(LogAttivita).order_by(*NEWEST_FIRST), paging)


def count_for_arnia(session: Session, id_arnia: int) -> int:
    return session.exec(
        select(func.count())
        .select_from(LogAttivita)
        .where(LogAttivita.id_arnia == id_arnia)
    ).one()


def insert(
    session: Session,
    *,
    id_utente: int | None,
    id_arnia: int,
    timestamp,
    tipo_attivita: str,
    descrizione: str | None,
    dati: dict | None,
) -> dict[str, Any]:
    """A null timestamp defaults to now, in the database."""
    voce = LogAttivita(
        id_utente=id_utente,
        id_arnia=id_arnia,
        timestamp=timestamp,
        tipo_attivita=tipo_attivita,
        descrizione=descrizione,
        dati=dati or None,
    )
    session.add(voce)
    session.flush()
    return as_dict(voce)


def owned(
    session: Session, id_log: int, id_arnia: int, id_utente: int
) -> LogAttivita | None:
    return session.exec(
        select(LogAttivita).where(
            LogAttivita.id_log == id_log,
            LogAttivita.id_arnia == id_arnia,
            LogAttivita.id_utente == id_utente,
        )
    ).first()


def find_owned(
    session: Session, id_log: int, id_arnia: int, id_utente: int
) -> dict[str, Any] | None:
    """Ownership probe: the activity must belong to both this arnia and this user."""
    voce = owned(session, id_log, id_arnia, id_utente)
    return {"id_log": voce.id_log} if voce else None


def get_all_columns(session: Session, id_log: int) -> dict[str, Any] | None:
    """Every column, for the empty-patch path that returns the row unchanged."""
    return as_dict(session.get(LogAttivita, id_log))


def update(
    session: Session, id_log: int, updates: dict[str, Any]
) -> dict[str, Any] | None:
    unknown = set(updates) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Colonne non aggiornabili: {sorted(unknown)}")

    voce = session.get(LogAttivita, id_log)
    if voce is None:
        return None
    for column, value in updates.items():
        setattr(voce, column, value)
    session.flush()
    return as_dict(voce)


def delete_owned(
    session: Session, id_log: int, id_arnia: int, id_utente: int
) -> dict[str, Any] | None:
    voce = owned(session, id_log, id_arnia, id_utente)
    if voce is None:
        return None
    session.delete(voce)
    session.flush()
    return {"id_log": id_log}
