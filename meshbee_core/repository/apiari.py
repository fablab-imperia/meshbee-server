"""Queries on `apiari`, and which of them a user can see through their hives."""

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from meshbee_core.models import Apiario, Arnia, UtenteArnia
from meshbee_core.repository import as_dict, as_dicts

# The apiari holding at least one active arnia the user has an active
# association with. Access is granted per hive (`utenti_arnie`), never per
# apiary, so this is the whole of what "visible" means.
_VISIBLE_IDS = (
    select(Arnia.id_apiario)
    .join(UtenteArnia, UtenteArnia.id_arnia == Arnia.id_arnia)
    .where(UtenteArnia.attivo.is_(True), Arnia.attiva.is_(True))
)


def _visible_to(id_utente: int):
    return _VISIBLE_IDS.where(UtenteArnia.id_utente == id_utente)


def get(session: Session, id_apiario: int) -> dict[str, Any] | None:
    return as_dict(session.get(Apiario, id_apiario))


def list_all(session: Session) -> list[dict[str, Any]]:
    return as_dicts(session.exec(select(Apiario).order_by(Apiario.id_apiario)).all())


def list_attivi(session: Session) -> list[dict[str, Any]]:
    return as_dicts(
        session.exec(
            select(Apiario)
            .where(Apiario.attivo.is_(True))
            .order_by(Apiario.nome_apiario)
        ).all()
    )


def list_for_utente(session: Session, id_utente: int) -> list[dict[str, Any]]:
    return as_dicts(
        session.exec(
            select(Apiario)
            .where(
                Apiario.attivo.is_(True),
                Apiario.id_apiario.in_(_visible_to(id_utente)),
            )
            .order_by(Apiario.nome_apiario)
        ).all()
    )


def is_visible_to(session: Session, id_utente: int, id_apiario: int) -> bool:
    """Whether the apiary holds a hive the user may read. Says nothing of `attivo`."""
    found = session.exec(
        _visible_to(id_utente).where(Arnia.id_apiario == id_apiario).limit(1)
    ).first()
    return found is not None


def count_arnie_attive(session: Session, id_apiario: int) -> int:
    return session.exec(
        select(func.count())
        .select_from(Arnia)
        .where(Arnia.id_apiario == id_apiario, Arnia.attiva.is_(True))
    ).one()


def insert(
    session: Session,
    *,
    nome_apiario: str,
    descrizione: str | None = None,
    posizione: str | None = None,
    latitudine=None,
    longitudine=None,
    id_utente_proprietario: int | None = None,
    metadati: dict | None = None,
) -> dict[str, Any]:
    apiario = Apiario(
        nome_apiario=nome_apiario,
        descrizione=descrizione,
        posizione=posizione,
        latitudine=latitudine,
        longitudine=longitudine,
        id_utente_proprietario=id_utente_proprietario,
        attivo=True,
        metadati=metadati or None,
    )
    session.add(apiario)
    session.flush()
    return as_dict(apiario)


def update(session: Session, id_apiario: int, **changes) -> dict[str, Any] | None:
    """
    Partial update: a None value (or an empty metadati) leaves the column untouched.

    `data_disattivazione` follows `attivo`: stamped when it is switched off,
    cleared when it is switched back on, so a revived apiary does not keep the
    date of a removal that no longer holds.
    """
    apiario = session.get(Apiario, id_apiario)
    if apiario is None:
        return None

    attivo = changes.get("attivo")
    if attivo is not None and attivo != apiario.attivo:
        apiario.data_disattivazione = None if attivo else func.now()

    metadati = changes.pop("metadati", None)
    for column, value in changes.items():
        if value is not None:
            setattr(apiario, column, value)
    if metadati:
        apiario.metadati = metadati
    session.flush()
    return as_dict(apiario)


def deactivate(session: Session, id_apiario: int) -> dict[str, Any] | None:
    apiario = session.get(Apiario, id_apiario)
    if apiario is None:
        return None
    apiario.attivo = False
    apiario.data_disattivazione = func.now()
    session.flush()
    return {"id_apiario": apiario.id_apiario}
