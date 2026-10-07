"""Queries on `nodi`."""
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from meshbee_core.models import Nodo
from meshbee_core.repository import as_dict, as_dicts


def list_all(session: Session) -> List[Dict[str, Any]]:
    return as_dicts(session.exec(select(Nodo).order_by(Nodo.id_nodo)).all())


def get(session: Session, id_nodo: str) -> Optional[Dict[str, Any]]:
    return as_dict(session.get(Nodo, id_nodo))


def find_id(session: Session, id_nodo: str) -> Optional[Dict[str, Any]]:
    found = session.exec(select(Nodo.id_nodo).where(Nodo.id_nodo == id_nodo)).first()
    return {"id_nodo": found} if found is not None else None


def insert(session: Session, *, id_nodo: str, nome_nodo: Optional[str], descrizione: Optional[str],
           posizione: Optional[str], configurazione: Optional[dict]) -> Dict[str, Any]:
    nodo = Nodo(
        id_nodo=id_nodo, nome_nodo=nome_nodo, descrizione=descrizione, posizione=posizione,
        attivo=True, configurazione=configurazione or None,
    )
    session.add(nodo)
    session.flush()
    return as_dict(nodo)


def update(session: Session, id_nodo: str, *, nome_nodo: Optional[str], descrizione: Optional[str],
           posizione: Optional[str], configurazione: Optional[dict]) -> Optional[Dict[str, Any]]:
    """Partial update: a None argument (or an empty configurazione) leaves the column untouched."""
    nodo = session.get(Nodo, id_nodo)
    if nodo is None:
        return None

    for column, value in (("nome_nodo", nome_nodo), ("descrizione", descrizione),
                          ("posizione", posizione)):
        if value is not None:
            setattr(nodo, column, value)
    if configurazione:
        nodo.configurazione = configurazione
    session.flush()
    return as_dict(nodo)


def deactivate(session: Session, id_nodo: str) -> Optional[Dict[str, Any]]:
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
    has registered it through the admin API.

    Deliberately does *not* write `ultimo_messaggio`: that column is owned by
    the `trigger_aggiorna_nodo` trigger on `letture`, which fires immediately
    after and overwrites whatever we put there.
    """
    session.exec(
        pg_insert(Nodo)
        .values(id_nodo=id_nodo, nome_nodo=nome_nodo, attivo=True)
        .on_conflict_do_nothing(index_elements=["id_nodo"])
    )
