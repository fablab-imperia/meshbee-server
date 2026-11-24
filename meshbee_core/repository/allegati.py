"""Queries on `allegati`, the stored files (#3)."""

from typing import Any

from sqlmodel import Session

from meshbee_core.models import Allegato
from meshbee_core.repository import as_dict


def insert(
    session: Session,
    *,
    chiave: str,
    content_type: str,
    dimensione: int,
    larghezza: int | None = None,
    altezza: int | None = None,
    id_utente_caricamento: int | None = None,
) -> dict[str, Any]:
    allegato = Allegato(
        chiave=chiave,
        content_type=content_type,
        dimensione=dimensione,
        larghezza=larghezza,
        altezza=altezza,
        id_utente_caricamento=id_utente_caricamento,
    )
    session.add(allegato)
    session.flush()
    return as_dict(allegato)


def get(session: Session, id_allegato: int) -> dict[str, Any] | None:
    return as_dict(session.get(Allegato, id_allegato))


def delete(session: Session, id_allegato: int) -> dict[str, Any] | None:
    """Remove the row and return it, for the caller to remove its file; None if gone."""
    allegato = session.get(Allegato, id_allegato)
    if allegato is None:
        return None
    row = as_dict(allegato)
    session.delete(allegato)
    session.flush()
    return row
