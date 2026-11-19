"""Turning a message from a node into a stored reading.

This sits on top of `services.letture.record_reading` rather than beside it,
because provisioning is where the two write paths legitimately differ: a node
may start transmitting before anyone registered it, so the ingest path creates
what it needs. The API's manual-insert endpoint refuses an unknown arnia
instead, and that difference is intentional.

Invalid measurements are the other intentional difference. The API refuses a
reading with an out-of-range value (the person typing it can fix it); a node
can't, and one faulty sensor must not cost the others. So ingest clears the
bad measurement, keeps the rest of the reading, and records what it discarded
in `dati_raw`.

Duplicates are the third (#4). The sender transmits every reading four times
about a second apart, and every receiver in range forwards its own copy, so one
measurement arrives several times with nothing to identify it by — no message
id, and often no timestamp. Ingest keeps one reading per arnia within a time
window and drops the rest. It is best effort by decision: an odd duplicate or
a lost reading is acceptable, a firmware change was not. The API never
deduplicates — a person typing a reading means it.
"""

import logging
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from meshbee_core.errors import NotFound
from meshbee_core.models import LetturaCreate
from meshbee_core.repository import arnie, nodi
from meshbee_core.repository import letture as letture_repo
from meshbee_core.services import arnie as arnie_service
from meshbee_core.services import letture

logger = logging.getLogger(__name__)

MEASUREMENTS = ("temperatura", "umidita", "peso", "batteria")


def clear_invalid_measurements(reading: dict[str, Any]) -> dict[str, Any]:
    """
    Null every measurement the reading model refuses, keeping the rest.

    Validation is the model's own, so the ranges stay declared once (limits.py).
    Each discarded value is kept as text under `dati_raw["discarded"]`, for
    whoever has to find the faulty sensor. Errors in anything but a measurement
    are left for `letture.record_reading` to report.
    """
    try:
        LetturaCreate(**reading)
        return reading
    except ValidationError as exc:
        bad = {
            err["loc"][0]
            for err in exc.errors()
            if err["loc"] and err["loc"][0] in MEASUREMENTS
        }
    if not bad:
        return reading

    discarded = {field: str(reading[field]) for field in sorted(bad)}
    logger.warning(
        f"Misure fuori limite azzerate per nodo {reading.get('id_nodo')}: {discarded}"
    )
    cleared = {**reading, **dict.fromkeys(bad)}
    dati_raw = reading.get("dati_raw")
    # A dati_raw that isn't an object is invalid in itself: left as it is, for
    # record_reading to refuse.
    if dati_raw is None or isinstance(dati_raw, dict):
        cleared["dati_raw"] = {**(dati_raw or {}), "discarded": discarded}
    return cleared


def log_dropped_duplicate(
    reading: dict[str, Any], id_sensore, kept: dict[str, Any]
) -> None:
    """
    One INFO line per dropped copy, with what was dropped and what it matched.

    Enough to tell retransmissions (seconds apart) from a node reporting
    faster than the window (minutes apart) without opening the database.
    """
    timestamp = reading["timestamp"] or "assente (ora di ricezione)"
    logger.info(
        f"Lettura duplicata ignorata per arnia {reading['id_arnia']} "
        f"(nodo: {reading['id_nodo']}, sensore: {id_sensore}, "
        f"timestamp: {timestamp}, "
        f"T: {reading['temperatura']}°C, "
        f"H: {reading['umidita']}%, "
        f"W: {reading['peso']}kg, "
        f"B: {reading['batteria']}V) — "
        f"già presente la lettura {kept['id_lettura']} delle {kept['timestamp']}"
    )


def register_node_and_resolve_arnia(session, id_nodo: str, id_sensore) -> int:
    """
    Record that the node was heard from, and find the arnia the reading is for.

    Creates the arnia when the node reports a sensor id we have never seen.
    Without a sensor id there is nothing to create *from*, so it falls back to
    the node's first arnia.

    Raises:
        NotFound: se non è possibile determinare l'arnia.
    """
    # Registration only: the node counts as heard from once its reading is
    # stored, in `record_node_reading`.
    nodi.register_if_absent(session, id_nodo, f"Nodo {id_nodo}")

    if id_sensore:
        found = arnie.find_id_by_nodo_sensore(session, id_nodo, id_sensore)
        if found:
            return found["id_arnia"]

        created = arnie.insert(
            session,
            id_nodo=id_nodo,
            id_sensore_fisico=id_sensore,
            nome_arnia=f"Arnia {id_nodo}-{id_sensore}",
            # The node owner's default apiary, or none while it is unassigned.
            id_apiario=arnie_service.placement(session, id_nodo, None),
        )
        logger.info(f"Creata nuova arnia: {created['id_arnia']}")
        return created["id_arnia"]

    found = arnie.find_first_id_by_nodo(session, id_nodo)
    if found:
        return found["id_arnia"]

    # Raising rather than returning None matters: the caller's session commits on
    # a clean exit, so a quiet return would persist the node upsert above. The
    # handler used to roll back by hand here.
    raise NotFound(f"Impossibile determinare id_arnia per nodo {id_nodo}")


def record_node_reading(
    session, payload: dict[str, Any], dedup_window: timedelta | None = None
) -> dict[str, Any] | None:
    """
    Store one reading from a node, provisioning the nodo and arnia as needed,
    and stamp the node's `ultimo_messaggio` with the time it was received.

    With a `dedup_window`, a reading that falls within it of one the arnia
    already has is a duplicate: nothing is stored and None is returned, but
    the node is still stamped — it was heard. The check reads before it
    writes, so two handlers running at once could both store a copy; there is
    one, and paho delivers its messages one at a time.

    Only this path stamps it: a message from the node is what "ultimo
    messaggio" means. A reading entered through the API is not one, so it
    leaves the column alone.

    An invalid measurement does not refuse the reading: it is stored as null
    (see `clear_invalid_measurements`).

    Raises:
        NotFound: se l'arnia non è determinabile.
        InvalidData: se la lettura resta invalida per altri motivi.
    """
    id_nodo = payload["id_nodo"]
    id_arnia = register_node_and_resolve_arnia(
        session, id_nodo, payload.get("id_sensore")
    )

    reading = {
        "id_arnia": id_arnia,
        "id_nodo": id_nodo,
        "timestamp": payload.get("timestamp"),
        "temperatura": payload.get("temperatura"),
        "umidita": payload.get("umidita"),
        "peso": payload.get("peso"),
        # The wire key is `bat`; everything past this point calls it batteria.
        "batteria": payload.get("bat"),
        "dati_raw": payload.get("dati_raw"),
    }
    kept = dedup_window and letture_repo.find_near(
        session, id_arnia, reading["timestamp"], dedup_window
    )
    if kept:
        log_dropped_duplicate(reading, payload.get("id_sensore"), kept)
        nodi.touch_ultimo_messaggio(session, id_nodo)
        return None

    lettura = letture.record_reading(session, clear_invalid_measurements(reading))
    # After the reading, inside the same transaction: a message that is
    # refused rolls this back with everything else.
    nodi.touch_ultimo_messaggio(session, id_nodo)
    return lettura
