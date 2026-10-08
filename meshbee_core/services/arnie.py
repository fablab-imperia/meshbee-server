"""Hives, and the state that carries their latest readings."""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import Conflict, NotFound
from meshbee_core.repository import apiari, arnie


def list_for_utente(
    session, current_user, id_apiario: int | None = None
) -> list[dict[str, Any]]:
    """
    Every active arnia for an admin, only the associated ones for a user.

    The admin branch is not a shortcut around the association table: an admin
    is expected to see hives nobody has been granted access to yet.

    Each hive carries the caller's own apiary for it, and `id_apiario` narrows
    the list to one of the caller's apiaries. Someone else's apiary just
    matches nothing: apiaries are per user.
    """
    if current_user["ruolo"] == "admin":
        rows = arnie.list_stato_attive(session, current_user["id_utente"], id_apiario)
    else:
        rows = arnie.list_stato_for_utente(
            session, current_user["id_utente"], id_apiario
        )
    return [dict(row) for row in rows]


def list_all(session, id_apiario: int | None = None) -> list[dict[str, Any]]:
    """
    Every arnia including the retired ones — the admin inventory.

    With `id_apiario`, the hives its owner has put in that apiary instead.

    Raises:
        NotFound: if `id_apiario` names no apiary.
    """
    if id_apiario is None:
        return [dict(row) for row in arnie.list_stato(session)]
    apiario = apiari.get(session, id_apiario)
    if not apiario:
        raise NotFound("Apiario non trovato")
    return arnie.list_stato_in_apiario(
        session, apiario["id_utente_proprietario"], id_apiario
    )


def list_ids(session) -> list[int]:
    """Every arnia id, oldest first — for callers that only need to iterate."""
    return [row["id_arnia"] for row in arnie.list_ids(session)]


def get_arnia(session, id_arnia: int, id_utente: int | None = None) -> dict[str, Any]:
    """
    With `id_utente`, the hive carries the apiary that user has put it in.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    row = arnie.get_stato(session, id_arnia, id_utente)
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def create_arnia(session, arnia) -> dict[str, Any]:
    """
    Raises:
        Conflict: se il sensore è già registrato per quel nodo.
        NotFound: se il nodo non esiste.
    """
    conflict = Conflict(
        f"Sensore '{arnia.id_sensore_fisico}' già registrato per il nodo '{arnia.id_nodo}'"
    )
    with integrity_errors(
        unique=conflict, foreign_key=NotFound(f"Nodo '{arnia.id_nodo}' non trovato")
    ):
        return dict(
            arnie.insert(
                session,
                id_nodo=arnia.id_nodo,
                id_sensore_fisico=arnia.id_sensore_fisico,
                # Same default the ingest path uses, so a hive created either way
                # is named identically.
                nome_arnia=arnia.nome_arnia
                or f"Arnia {arnia.id_nodo}-{arnia.id_sensore_fisico}",
                descrizione=arnia.descrizione,
                posizione=arnia.posizione,
                latitudine=arnia.latitudine,
                longitudine=arnia.longitudine,
                metadati=arnia.metadati,
            )
        )


def update_arnia(
    session, id_arnia: int, arnia, *, allow_attiva: bool = False
) -> dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    `allow_attiva` is what separates the two update endpoints: a user with write
    permission may edit a hive's details but not retire or revive it.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    optional = {"attiva": arnia.attiva} if allow_attiva else {}

    row = arnie.update(
        session,
        id_arnia,
        nome_arnia=arnia.nome_arnia,
        descrizione=arnia.descrizione,
        posizione=arnia.posizione,
        latitudine=arnia.latitudine,
        longitudine=arnia.longitudine,
        metadati=arnia.metadati,
        **optional,
    )
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def deactivate_arnia(session, id_arnia: int) -> None:
    """
    Soft delete: historical readings are kept.

    Raises:
        NotFound: se l'arnia non esiste.
    """
    if not arnie.deactivate(session, id_arnia):
        raise NotFound("Arnia non trovata")
