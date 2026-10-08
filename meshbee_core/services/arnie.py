"""Hives, and the state that carries their latest readings."""

from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import Conflict, InvalidData, NotFound
from meshbee_core.repository import apiari, arnie


def list_for_utente(
    session, current_user, id_apiario: int | None = None
) -> list[dict[str, Any]]:
    """
    Every active arnia for an admin, only the associated ones for a user.

    The admin branch is not a shortcut around the association table: an admin
    is expected to see hives nobody has been granted access to yet.

    `id_apiario` narrows either list to one apiary. It needs no access check of
    its own: a user still only gets the hives they are associated with.
    """
    if current_user["ruolo"] == "admin":
        rows = arnie.list_stato_attive(session, id_apiario)
    else:
        rows = arnie.list_stato_for_utente(
            session, current_user["id_utente"], id_apiario
        )
    return [dict(row) for row in rows]


def list_all(session, id_apiario: int | None = None) -> list[dict[str, Any]]:
    """Every arnia including the retired ones — the admin inventory."""
    return [dict(row) for row in arnie.list_stato(session, id_apiario)]


def list_ids(session) -> list[int]:
    """Every arnia id, oldest first — for callers that only need to iterate."""
    return [row["id_arnia"] for row in arnie.list_ids(session)]


def get_arnia(session, id_arnia: int) -> dict[str, Any]:
    """
    Raises:
        NotFound: se l'arnia non esiste.
    """
    row = arnie.get_stato(session, id_arnia)
    if not row:
        raise NotFound("Arnia non trovata")
    return dict(row)


def create_arnia(session, arnia) -> dict[str, Any]:
    """
    Raises:
        Conflict: se il sensore è già registrato per quel nodo.
        NotFound: se il nodo non esiste.
    """
    check_apiario(session, arnia.id_apiario)
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
                id_apiario=arnia.id_apiario,
            )
        )


def update_arnia(
    session, id_arnia: int, arnia, current_user, *, allow_attiva: bool = False
) -> dict[str, Any]:
    """
    Apply the supplied fields; unmentioned ones keep their stored value.

    `allow_attiva` is what separates the two update endpoints: a user with write
    permission may edit a hive's details but not retire or revive it.

    `id_apiario` moves the hive only when the request names it, so a client
    unaware of apiaries never takes a hive out of one; an explicit null does.

    Raises:
        NotFound: se l'arnia non esiste.
        InvalidData: if the hive cannot be moved into that apiary.
    """
    optional = {"attiva": arnia.attiva} if allow_attiva else {}
    if "id_apiario" in arnia.model_fields_set:
        check_apiario(session, arnia.id_apiario, current_user)
        optional["id_apiario"] = arnia.id_apiario

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


def check_apiario(session, id_apiario: int | None, current_user=None) -> None:
    """
    Refuse to put a hive in an apiary it may not go to. None always may.

    A non-admin may only use an apiary they can already see — one holding a
    hive they are associated with — and gets the same answer whether a hidden apiary
    exists or not, so the check reveals nothing about other people's apiaries.
    `current_user` None is the admin-only creation path.

    Raises:
        InvalidData: if the user cannot see the apiary, or it is retired.
        NotFound: if the apiary does not exist (admins only).
    """
    if id_apiario is None:
        return
    if (
        current_user is not None
        and current_user["ruolo"] != "admin"
        and not apiari.is_visible_to(session, current_user["id_utente"], id_apiario)
    ):
        raise InvalidData("Apiario non accessibile")
    apiario = apiari.get(session, id_apiario)
    if apiario is None:
        raise NotFound(f"Apiario {id_apiario} non trovato")
    if not apiario["attivo"]:
        raise InvalidData(f"Apiario {id_apiario} disattivato")
