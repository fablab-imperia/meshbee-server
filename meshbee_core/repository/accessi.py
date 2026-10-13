"""Who may do what: apiary ownership and the roles shared on `utenti_apiari`."""

from typing import Any

from sqlalchemy import Integer, cast, literal, null, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, delete, select

from meshbee_core.models import Apiario, Arnia, InvitoApiario, Utente, UtenteApiario
from meshbee_core.paging import EVERYTHING, Page, Paging
from meshbee_core.repository import fetch_page

PAIR = ["id_utente", "id_apiario"]

OWNER = "owner"


def _accesso(row, id_utente: int) -> str | None:
    """The access a (owner id, shared role) row gives the user."""
    if row is None:
        return None
    id_proprietario, ruolo = row
    return OWNER if id_proprietario == id_utente else ruolo


def accesso_su_apiario(session: Session, id_utente: int, id_apiario: int) -> str | None:
    row = session.exec(
        select(Apiario.id_utente_proprietario, UtenteApiario.ruolo)
        .outerjoin(
            UtenteApiario,
            (UtenteApiario.id_apiario == Apiario.id_apiario)
            & (UtenteApiario.id_utente == id_utente),
        )
        .where(Apiario.id_apiario == id_apiario)
    ).first()
    return _accesso(row, id_utente)


def accesso_su_arnia(session: Session, id_utente: int, id_arnia: int) -> str | None:
    """Through the hive's apiary; None for an unassigned hive, which only admins reach."""
    row = session.exec(
        select(Apiario.id_utente_proprietario, UtenteApiario.ruolo)
        .select_from(Arnia)
        .join(Apiario, Apiario.id_apiario == Arnia.id_apiario)
        .outerjoin(
            UtenteApiario,
            (UtenteApiario.id_apiario == Apiario.id_apiario)
            & (UtenteApiario.id_utente == id_utente),
        )
        .where(Arnia.id_arnia == id_arnia)
    ).first()
    return _accesso(row, id_utente)


# A share with the user it is for, as the owner sees it.
_CONDIVISIONE = select(
    UtenteApiario.id_utente,
    UtenteApiario.id_apiario,
    UtenteApiario.ruolo,
    UtenteApiario.data_condivisione,
    Utente.email,
).join(Utente, Utente.id_utente == UtenteApiario.id_utente)


def list_for_apiario(
    session: Session, id_apiario: int, paging: Paging = EVERYTHING
) -> Page:
    """
    The apiary's active shares and pending invitations (#40), as one list by email.

    Each row says which it is in `stato`, and carries `id_utente` or `id_invito`.
    """
    no_id = cast(null(), Integer)
    shares = (
        select(
            UtenteApiario.id_utente,
            no_id.label("id_invito"),
            UtenteApiario.id_apiario,
            UtenteApiario.ruolo,
            UtenteApiario.data_condivisione,
            Utente.email,
            literal("attiva").label("stato"),
        )
        .join(Utente, Utente.id_utente == UtenteApiario.id_utente)
        .where(UtenteApiario.id_apiario == id_apiario)
    )
    invites = select(
        no_id.label("id_utente"),
        InvitoApiario.id_invito,
        InvitoApiario.id_apiario,
        InvitoApiario.ruolo,
        InvitoApiario.data_invito.label("data_condivisione"),
        InvitoApiario.email,
        literal("in_attesa").label("stato"),
    ).where(InvitoApiario.id_apiario == id_apiario)
    both = union_all(shares, invites).subquery()
    # An email is either shared or invited on one apiary, never both; `stato`
    # still breaks a tie, so paging stays stable.
    return fetch_page(
        session,
        select(*both.c).order_by(both.c.email, both.c.stato),
        paging,
        lambda rows: [dict(row._mapping) for row in rows],
    )


def get(session: Session, id_utente: int, id_apiario: int) -> dict[str, Any] | None:
    row = session.exec(
        _CONDIVISIONE.where(
            UtenteApiario.id_utente == id_utente,
            UtenteApiario.id_apiario == id_apiario,
        )
    ).first()
    return dict(row._mapping) if row is not None else None


def upsert(session: Session, id_utente: int, id_apiario: int, ruolo: str) -> None:
    """Share the apiary, or change the role of an existing share."""
    statement = pg_insert(UtenteApiario).values(
        id_utente=id_utente, id_apiario=id_apiario, ruolo=ruolo
    )
    session.exec(
        statement.on_conflict_do_update(
            index_elements=PAIR, set_={"ruolo": statement.excluded.ruolo}
        )
    )


def update_ruolo(session: Session, id_utente: int, id_apiario: int, ruolo: str) -> bool:
    share = session.exec(
        select(UtenteApiario).where(
            UtenteApiario.id_utente == id_utente,
            UtenteApiario.id_apiario == id_apiario,
        )
    ).first()
    if share is None:
        return False
    share.ruolo = ruolo
    session.flush()
    return True


def delete_share(session: Session, id_utente: int, id_apiario: int) -> bool:
    result = session.exec(
        delete(UtenteApiario).where(
            UtenteApiario.id_utente == id_utente,
            UtenteApiario.id_apiario == id_apiario,
        )
    )
    return result.rowcount > 0
