"""Queries on `apiari`: the places a user's hives stand in."""

from typing import Any

from sqlalchemy import case, func, or_
from sqlmodel import Session, select

from meshbee_core.models import Apiario, Arnia, UtenteApiario
from meshbee_core.repository import as_dict, as_dicts
from meshbee_core.repository.accessi import OWNER


def get(session: Session, id_apiario: int) -> dict[str, Any] | None:
    return as_dict(session.get(Apiario, id_apiario))


def get_predefinito(session: Session, id_utente: int) -> dict[str, Any] | None:
    return as_dict(
        session.exec(
            select(Apiario).where(
                Apiario.id_utente_proprietario == id_utente,
                Apiario.predefinito.is_(True),
            )
        ).first()
    )


def list_all(session: Session, id_utente: int | None = None) -> list[dict[str, Any]]:
    """Every apiary, or one owner's; the default first, then by name."""
    query = select(Apiario)
    if id_utente is not None:
        query = query.where(Apiario.id_utente_proprietario == id_utente)
    return as_dicts(
        session.exec(
            query.order_by(
                Apiario.id_utente_proprietario,
                Apiario.predefinito.desc(),
                Apiario.nome_apiario,
                Apiario.id_apiario,
            )
        ).all()
    )


def _with_accesso(id_utente: int):
    """Apiaries with the user's access on each: "owner", a shared role, or None."""
    owned = Apiario.id_utente_proprietario == id_utente
    return (
        select(Apiario, case((owned, OWNER), else_=UtenteApiario.ruolo))
        .outerjoin(
            UtenteApiario,
            (UtenteApiario.id_apiario == Apiario.id_apiario)
            & (UtenteApiario.id_utente == id_utente),
        )
        .order_by(
            owned.desc(),
            Apiario.predefinito.desc(),
            Apiario.nome_apiario,
            Apiario.id_apiario,
        )
    ), owned


def _rows(session: Session, query) -> list[dict[str, Any]]:
    return [
        as_dict(apiario) | {"accesso": accesso}
        for apiario, accesso in session.exec(query).all()
    ]


def list_for_utente(session: Session, id_utente: int) -> list[dict[str, Any]]:
    """The apiaries the user owns, then those shared with them."""
    query, owned = _with_accesso(id_utente)
    return _rows(session, query.where(or_(owned, UtenteApiario.id.is_not(None))))


def get_for_utente(
    session: Session, id_apiario: int, id_utente: int
) -> dict[str, Any] | None:
    query, _ = _with_accesso(id_utente)
    rows = _rows(session, query.where(Apiario.id_apiario == id_apiario))
    return rows[0] if rows else None


def count_arnie_attive(session: Session, id_apiario: int) -> int:
    """Active hives still in it: what blocks deleting it."""
    return session.exec(
        select(func.count())
        .select_from(Arnia)
        .where(Arnia.id_apiario == id_apiario, Arnia.attiva.is_(True))
    ).one()


def insert(
    session: Session,
    *,
    id_utente_proprietario: int,
    nome_apiario: str,
    predefinito: bool = False,
    descrizione: str | None = None,
    posizione: str | None = None,
    latitudine=None,
    longitudine=None,
    metadati: dict | None = None,
) -> dict[str, Any]:
    apiario = Apiario(
        id_utente_proprietario=id_utente_proprietario,
        nome_apiario=nome_apiario,
        predefinito=predefinito,
        descrizione=descrizione,
        posizione=posizione,
        latitudine=latitudine,
        longitudine=longitudine,
        metadati=metadati or None,
    )
    session.add(apiario)
    session.flush()
    return as_dict(apiario)


def update(session: Session, id_apiario: int, **changes) -> dict[str, Any] | None:
    """Partial update: a None value (or an empty metadati) leaves the column untouched."""
    apiario = session.get(Apiario, id_apiario)
    if apiario is None:
        return None

    metadati = changes.pop("metadati", None)
    for column, value in changes.items():
        if value is not None:
            setattr(apiario, column, value)
    if metadati:
        apiario.metadati = metadati
    session.flush()
    return as_dict(apiario)


def delete(session: Session, id_apiario: int) -> dict[str, Any] | None:
    """Its shares go with it (ON DELETE CASCADE on `utenti_apiari`)."""
    apiario = session.get(Apiario, id_apiario)
    if apiario is None:
        return None
    session.delete(apiario)
    session.flush()
    return {"id_apiario": id_apiario}
