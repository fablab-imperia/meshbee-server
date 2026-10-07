"""Queries on `utenti`."""
from typing import Any, Dict, List, Optional

from sqlalchemy import func, update as sql_update
from sqlmodel import Session, select

from meshbee_core.models import Utente
from meshbee_core.repository import as_dict

# The public projection leaves out `password_hash`, so a response built straight
# from these rows cannot leak it.
PRIVATE = ("password_hash",)

CREDENTIALS = ("id_utente", "email", "password_hash", "nome", "cognome", "ruolo", "attivo")

# Columns `update` will accept. Anything else is a programming error, not user
# input.
UPDATABLE = ("email", "nome", "cognome", "ruolo", "attivo")


def by_email(session: Session, email: str) -> Optional[Utente]:
    return session.exec(select(Utente).where(Utente.email == email)).first()


def get_credentials_by_email(session: Session, email: str) -> Optional[Dict[str, Any]]:
    """The login projection: includes password_hash, unlike every other read."""
    return as_dict(by_email(session, email), only=CREDENTIALS)


def get_by_email(session: Session, email: str) -> Optional[Dict[str, Any]]:
    return as_dict(by_email(session, email), exclude=PRIVATE)


def touch_ultimo_accesso(session: Session, id_utente: int) -> None:
    session.exec(
        sql_update(Utente).where(Utente.id_utente == id_utente).values(ultimo_accesso=func.now())
    )


def get_ruolo(session: Session, id_utente: int) -> Optional[Dict[str, Any]]:
    ruolo = session.exec(select(Utente.ruolo).where(Utente.id_utente == id_utente)).first()
    return {"ruolo": ruolo} if ruolo is not None else None


def list_all(session: Session) -> List[Dict[str, Any]]:
    rows = session.exec(select(Utente).order_by(Utente.id_utente)).all()
    return [as_dict(row, exclude=PRIVATE) for row in rows]


def find_id_by_email(session: Session, email: str) -> Optional[Dict[str, Any]]:
    id_utente = session.exec(select(Utente.id_utente).where(Utente.email == email)).first()
    return {"id_utente": id_utente} if id_utente is not None else None


def insert(session: Session, *, email: str, password_hash: str, nome: str, cognome: str,
           ruolo: str) -> Dict[str, Any]:
    utente = Utente(
        email=email, password_hash=password_hash, nome=nome, cognome=cognome,
        ruolo=ruolo, attivo=True, data_attivazione=func.now(),
    )
    session.add(utente)
    session.flush()
    return as_dict(utente, exclude=PRIVATE)


def update(session: Session, id_utente: int, updates: Dict[str, Any], *,
           stamp_disattivazione: bool = False) -> Optional[Dict[str, Any]]:
    """
    Apply the named columns and return the updated row, or None if absent.

    `stamp_disattivazione` adds the data_disattivazione side effect; whether it
    applies is the service's call, not this layer's.
    """
    unknown = set(updates) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"Colonne non aggiornabili: {sorted(unknown)}")

    utente = session.get(Utente, id_utente)
    if utente is None:
        return None

    for column, value in updates.items():
        setattr(utente, column, value)
    if stamp_disattivazione:
        utente.data_disattivazione = func.now()
    session.flush()
    return as_dict(utente, exclude=PRIVATE)


def deactivate(session: Session, id_utente: int) -> Optional[Dict[str, Any]]:
    utente = session.get(Utente, id_utente)
    if utente is None:
        return None
    utente.attivo = False
    utente.data_disattivazione = func.now()
    session.flush()
    return {"id_utente": utente.id_utente}


def get_password_hash(session: Session, id_utente: int) -> Optional[Dict[str, Any]]:
    password_hash = session.exec(
        select(Utente.password_hash).where(Utente.id_utente == id_utente)
    ).first()
    return {"password_hash": password_hash} if password_hash is not None else None


def set_password_hash(session: Session, id_utente: int, password_hash: str) -> Optional[Dict[str, Any]]:
    utente = session.get(Utente, id_utente)
    if utente is None:
        return None
    utente.password_hash = password_hash
    session.flush()
    return {"id_utente": utente.id_utente}
