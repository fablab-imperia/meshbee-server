"""Queries on `nodi`."""

from typing import Any

from sqlalchemy import func
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from meshbee_core.models import Nodo
from meshbee_core.repository import as_dict, as_dicts


def list_all(session: Session) -> list[dict[str, Any]]:
    return as_dicts(session.exec(select(Nodo).order_by(Nodo.id_nodo)).all())


def get(session: Session, id_nodo: str) -> dict[str, Any] | None:
    return as_dict(session.get(Nodo, id_nodo))


def find_id(session: Session, id_nodo: str) -> dict[str, Any] | None:
    found = session.exec(select(Nodo.id_nodo).where(Nodo.id_nodo == id_nodo)).first()
    return {"id_nodo": found} if found is not None else None


def insert(
    session: Session,
    *,
    id_nodo: str,
    nome_nodo: str | None,
    descrizione: str | None,
    posizione: str | None,
    configurazione: dict | None,
) -> dict[str, Any]:
    nodo = Nodo(
        id_nodo=id_nodo,
        nome_nodo=nome_nodo,
        descrizione=descrizione,
        posizione=posizione,
        attivo=True,
        configurazione=configurazione or None,
    )
    session.add(nodo)
    session.flush()
    return as_dict(nodo)


def update(
    session: Session,
    id_nodo: str,
    *,
    nome_nodo: str | None,
    descrizione: str | None,
    posizione: str | None,
    configurazione: dict | None,
) -> dict[str, Any] | None:
    """Partial update: a None argument (or an empty configurazione) leaves the column untouched."""
    nodo = session.get(Nodo, id_nodo)
    if nodo is None:
        return None

    for column, value in (
        ("nome_nodo", nome_nodo),
        ("descrizione", descrizione),
        ("posizione", posizione),
    ):
        if value is not None:
            setattr(nodo, column, value)
    if configurazione:
        nodo.configurazione = configurazione
    session.flush()
    return as_dict(nodo)


def deactivate(session: Session, id_nodo: str) -> dict[str, Any] | None:
    nodo = session.get(Nodo, id_nodo)
    if nodo is None:
        return None
    nodo.attivo = False
    session.flush()
    return {"id_nodo": nodo.id_nodo}


def register_if_absent(session: Session, id_nodo: str, nome_nodo: str) -> None:
    """
    Make sure the node exists, leaving an already-registered one untouched.

    Used by the ingest path, where a node may start transmitting before anyone
    has registered it through the admin API. Registering is not hearing from
    it: `ultimo_messaggio` is `touch_ultimo_messaggio`'s, once a reading has
    actually been stored.
    """
    session.exec(
        pg_insert(Nodo)
        .values(id_nodo=id_nodo, nome_nodo=nome_nodo, attivo=True)
        .on_conflict_do_nothing(index_elements=["id_nodo"])
    )


def touch_ultimo_messaggio(session: Session, id_nodo: str) -> None:
    """
    Record that the node was heard from just now — the database's clock.

    The server's time, never the reading's: a node with a wrong clock, or a
    replay of buffered readings, must not move "last heard from" backwards.
    """
    session.exec(
        sql_update(Nodo)
        .where(Nodo.id_nodo == id_nodo)
        .values(ultimo_messaggio=func.now())
    )


def set_proprietario(
    session: Session, id_nodo: str, id_utente: int | None
) -> dict[str, Any] | None:
    nodo = session.get(Nodo, id_nodo)
    if nodo is None:
        return None
    nodo.id_proprietario = id_utente
    session.flush()
    return as_dict(nodo)
