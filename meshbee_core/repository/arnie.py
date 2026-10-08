"""Queries on `arnie`, and the hive state with its latest reading."""

from typing import Any

from sqlalchemy import case, func, or_, true
from sqlalchemy import update as sql_update
from sqlmodel import Session, select

from meshbee_core.models import Apiario, Arnia, Lettura, Nodo, UtenteApiario
from meshbee_core.repository import as_dict, mapping
from meshbee_core.repository.accessi import OWNER

# Sentinel for "leave this column alone entirely", which is not the same as
# passing None (which also leaves it alone, but for every other column).
UNSET = object()

# The most recent reading of the arnia in the outer query. LATERAL, so it runs
# once per arnia and every "ultimo" value comes from the same row.
_latest = (
    select(
        Lettura.temperatura,
        Lettura.umidita,
        Lettura.peso,
        Lettura.batteria,
        Lettura.timestamp,
    )
    .where(Lettura.id_arnia == Arnia.id_arnia)
    .order_by(Lettura.timestamp.desc())
    .limit(1)
    .lateral("ultima")
)

# An arnia with its node's name and its current state: what the hive list shows.
# The columns are those of the former `v_arnie_stato` view, in the same order,
# followed by the hive's apiary.
STATO = (
    select(
        Arnia.id_arnia,
        Arnia.id_nodo,
        Arnia.id_sensore_fisico,
        Arnia.nome_arnia,
        Nodo.nome_nodo,
        Arnia.posizione,
        Arnia.latitudine,
        Arnia.longitudine,
        Arnia.data_installazione,
        Arnia.data_rimozione,
        Arnia.attiva,
        Arnia.metadati,
        _latest.c.temperatura.label("ultima_temperatura"),
        _latest.c.umidita.label("ultima_umidita"),
        _latest.c.peso.label("ultimo_peso"),
        _latest.c.timestamp.label("ultimo_aggiornamento"),
        _latest.c.batteria.label("ultima_batteria"),
        Arnia.id_apiario,
        Apiario.nome_apiario,
    )
    .select_from(Arnia)
    .outerjoin(Nodo, Nodo.id_nodo == Arnia.id_nodo)
    .outerjoin(Apiario, Apiario.id_apiario == Arnia.id_apiario)
    .outerjoin(_latest, true())
)


def stato_rows(session: Session, query) -> list[dict[str, Any]]:
    return [mapping(row) for row in session.exec(query).all()]


def with_accesso(query, id_utente: int, *, accessible_only: bool):
    """
    Add what the user may do on each hive: "owner" when its apiary is theirs,
    else the role shared with them on it, else None.

    `accessible_only` keeps just the hives with some access.
    """
    owned = Apiario.id_utente_proprietario == id_utente
    query = query.add_columns(
        case((owned, OWNER), else_=UtenteApiario.ruolo).label("accesso")
    ).outerjoin(
        UtenteApiario,
        (UtenteApiario.id_apiario == Arnia.id_apiario)
        & (UtenteApiario.id_utente == id_utente),
    )
    if accessible_only:
        query = query.where(or_(owned, UtenteApiario.id.is_not(None)))
    return query


def in_apiario(query, id_apiario: int | None):
    """Narrow to one apiary; None leaves the query unfiltered."""
    return query if id_apiario is None else query.where(Arnia.id_apiario == id_apiario)


def list_stato(session: Session, id_apiario: int | None = None) -> list[dict[str, Any]]:
    return stato_rows(session, in_apiario(STATO, id_apiario).order_by(Arnia.id_arnia))


def list_stato_attive(
    session: Session, id_utente: int, id_apiario: int | None = None
) -> list[dict[str, Any]]:
    """Every active arnia, with what `id_utente` may do on each."""
    return stato_rows(
        session,
        with_accesso(in_apiario(STATO, id_apiario), id_utente, accessible_only=False)
        .where(Arnia.attiva.is_(True))
        .order_by(Arnia.nome_arnia),
    )


def list_stato_for_utente(
    session: Session, id_utente: int, id_apiario: int | None = None
) -> list[dict[str, Any]]:
    """The active hives the user owns or has been shared, through their apiary."""
    return stato_rows(
        session,
        with_accesso(in_apiario(STATO, id_apiario), id_utente, accessible_only=True)
        .where(Arnia.attiva.is_(True))
        .order_by(Arnia.nome_arnia),
    )


def get_stato(
    session: Session, id_arnia: int, id_utente: int | None = None
) -> dict[str, Any] | None:
    """One arnia; with `id_utente`, also what that user may do on it."""
    query = STATO
    if id_utente is not None:
        query = with_accesso(query, id_utente, accessible_only=False)
    return mapping(session.exec(query.where(Arnia.id_arnia == id_arnia)).first())


def list_ids(session: Session) -> list[dict[str, Any]]:
    """
    Just the identifiers, for callers that only need to iterate.

    Distinct from `list_stato` on purpose: that query also fetches each arnia's
    latest reading, which is wasted work when nobody is going to look at it.
    """
    ids = session.exec(select(Arnia.id_arnia).order_by(Arnia.id_arnia)).all()
    return [{"id_arnia": id_arnia} for id_arnia in ids]


def insert(
    session: Session,
    *,
    id_nodo: str,
    id_sensore_fisico: str,
    nome_arnia: str,
    descrizione: str | None = None,
    posizione: str | None = None,
    latitudine=None,
    longitudine=None,
    metadati: dict | None = None,
    id_apiario: int | None = None,
) -> dict[str, Any]:
    arnia = Arnia(
        id_nodo=id_nodo,
        id_sensore_fisico=id_sensore_fisico,
        nome_arnia=nome_arnia,
        descrizione=descrizione,
        posizione=posizione,
        latitudine=latitudine,
        longitudine=longitudine,
        attiva=True,
        metadati=metadati or None,
        id_apiario=id_apiario,
    )
    session.add(arnia)
    session.flush()
    return as_dict(arnia)


def update(
    session: Session,
    id_arnia: int,
    *,
    nome_arnia=None,
    descrizione=None,
    posizione=None,
    latitudine=None,
    longitudine=None,
    metadati=None,
    attiva=UNSET,
) -> dict[str, Any] | None:
    """
    Partial update: a None argument (or an empty metadati) leaves the column untouched.

    `attiva` is ignored unless explicitly passed — the user endpoint must not be
    able to reactivate or retire an arnia, only the admin one can. Passed as
    None it is left untouched too, like every other column.
    """
    arnia = session.get(Arnia, id_arnia)
    if arnia is None:
        return None

    changes = {
        "nome_arnia": nome_arnia,
        "descrizione": descrizione,
        "posizione": posizione,
        "latitudine": latitudine,
        "longitudine": longitudine,
    }
    if attiva is not UNSET:
        changes["attiva"] = attiva
    for column, value in changes.items():
        if value is not None:
            setattr(arnia, column, value)
    if metadati:
        arnia.metadati = metadati
    session.flush()
    return as_dict(arnia)


def deactivate(session: Session, id_arnia: int) -> dict[str, Any] | None:
    arnia = session.get(Arnia, id_arnia)
    if arnia is None:
        return None
    arnia.attiva = False
    arnia.data_rimozione = func.now()
    session.flush()
    return {"id_arnia": arnia.id_arnia}


def find_id_by_nodo_sensore(
    session: Session, id_nodo: str, id_sensore: str
) -> dict[str, Any] | None:
    found = session.exec(
        select(Arnia.id_arnia).where(
            Arnia.id_nodo == id_nodo, Arnia.id_sensore_fisico == id_sensore
        )
    ).first()
    return {"id_arnia": found} if found is not None else None


def find_first_id_by_nodo(session: Session, id_nodo: str) -> dict[str, Any] | None:
    """Fallback for readings that carry no sensor id: the node's lowest arnia."""
    found = session.exec(
        select(Arnia.id_arnia)
        .where(Arnia.id_nodo == id_nodo)
        .order_by(Arnia.id_arnia)
        .limit(1)
    ).first()
    return {"id_arnia": found} if found is not None else None


def set_apiario(
    session: Session, id_arnia: int, id_apiario: int
) -> dict[str, Any] | None:
    arnia = session.get(Arnia, id_arnia)
    if arnia is None:
        return None
    arnia.id_apiario = id_apiario
    session.flush()
    return as_dict(arnia)


def move_all(session: Session, from_apiario: int, to_apiario: int) -> None:
    """Every hive of one apiary, retired ones included, into another."""
    session.exec(
        sql_update(Arnia)
        .where(Arnia.id_apiario == from_apiario)
        .values(id_apiario=to_apiario)
    )


def place_nodo(session: Session, id_nodo: str, id_apiario: int | None) -> None:
    """Every hive of a node into one apiary, or (None) into none."""
    session.exec(
        sql_update(Arnia).where(Arnia.id_nodo == id_nodo).values(id_apiario=id_apiario)
    )


def get_proprietario(session: Session, id_arnia: int) -> dict[str, Any] | None:
    """The hive's owner, through its apiary; None if the hive does not exist."""
    row = session.exec(
        select(Arnia.id_arnia, Apiario.id_utente_proprietario)
        .outerjoin(Apiario, Apiario.id_apiario == Arnia.id_apiario)
        .where(Arnia.id_arnia == id_arnia)
    ).first()
    return mapping(row)
