"""Queries on `apiari`, each user's own grouping of their hives."""

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from meshbee_core.models import Apiario, Arnia, UtenteArnia
from meshbee_core.repository import as_dict, as_dicts


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
    """Every apiary, or one user's; the default first, then by name."""
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


def count_arnie_attive(session: Session, id_apiario: int) -> int:
    """Active hives its owner still has in it: what blocks deleting it."""
    return session.exec(
        select(func.count())
        .select_from(UtenteArnia)
        .join(Arnia, Arnia.id_arnia == UtenteArnia.id_arnia)
        .where(
            UtenteArnia.id_apiario == id_apiario,
            UtenteArnia.attivo.is_(True),
            Arnia.attiva.is_(True),
        )
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
    apiario = session.get(Apiario, id_apiario)
    if apiario is None:
        return None
    session.delete(apiario)
    session.flush()
    return {"id_apiario": id_apiario}
