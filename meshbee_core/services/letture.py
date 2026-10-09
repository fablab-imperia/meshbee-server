"""Readings: recording, correcting and deleting them, and reading them back as lists or chart series."""

from datetime import datetime, timedelta
from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.models import LetturaCreate, LetturaUpdate
from meshbee_core.paging import Page, Paging
from meshbee_core.repository import letture

# How far back a query reaches when the caller gives no start date.
DEFAULT_WINDOW_DAYS = 365


def default_window(data_inizio, data_fine):
    """Fill in the ends of an open date range: last year, up to now."""
    if not data_inizio:
        data_inizio = datetime.now() - timedelta(days=DEFAULT_WINDOW_DAYS)
    if not data_fine:
        data_fine = datetime.now()
    return data_inizio, data_fine


def record_reading(session, data: LetturaCreate | dict[str, Any]) -> dict[str, Any]:
    """
    Validate and persist a single reading.

    Both entry points come through here, which is the point of the whole layer:
    the API hands over a model FastAPI already validated (so this re-validation
    is a no-op), and the MQTT handler hands over a parsed payload that nothing
    has checked yet. Routing both through one function is what stops the two
    paths drifting the next time the payload format changes.

    Raises:
        InvalidData: se la lettura non rispetta i limiti dichiarati.
    """
    if isinstance(data, LetturaCreate):
        lettura = data
    else:
        try:
            lettura = LetturaCreate(**data)
        except ValueError as exc:
            # Out-of-range measurements used to reach Postgres and be refused by
            # a CHECK constraint, which the ingest path logged and rolled back —
            # the reading was simply lost. Refusing here says what was wrong.
            raise InvalidData(f"Lettura non valida: {exc}") from exc

    with integrity_errors(
        foreign_key=NotFound(f"Arnia {lettura.id_arnia} non trovata")
    ):
        return letture.insert(
            session,
            id_arnia=lettura.id_arnia,
            id_nodo=lettura.id_nodo,
            timestamp=lettura.timestamp,
            temperatura=lettura.temperatura,
            umidita=lettura.umidita,
            peso=lettura.peso,
            batteria=lettura.batteria,
            dati_raw=lettura.dati_raw,
        )


def list_for_arnia(
    session, id_arnia: int, data_inizio, data_fine, paging: Paging
) -> Page:
    data_inizio, data_fine = default_window(data_inizio, data_fine)
    return letture.list_by_arnia(session, id_arnia, data_inizio, data_fine, paging)


def list_all(session, paging: Paging) -> Page:
    return letture.list_all(session, paging)


def update_lettura(session, id_lettura: int, changes: LetturaUpdate) -> dict[str, Any]:
    """
    Apply the fields the caller sent; a measurement sent as null is cleared.

    Raises:
        NotFound: if the reading does not exist.
    """
    updates = changes.model_dump(exclude_unset=True)
    if updates:
        row = letture.update(session, id_lettura, updates)
    else:
        # Nothing to change: hand back the row as it stands.
        row = letture.get(session, id_lettura)
    if not row:
        raise NotFound("Lettura non trovata")
    return dict(row)


def delete_lettura(session, id_lettura: int) -> None:
    """
    Raises:
        NotFound: if the reading does not exist.
    """
    if not letture.delete_by_ids(session, [id_lettura]):
        raise NotFound("Lettura non trovata")


def delete_letture(session, ids: list[int]) -> int:
    """
    Delete readings by id; returns how many were deleted.

    Ids that do not exist are skipped rather than refused: the caller picked
    them from a listing, and a reading already gone is the outcome it wanted.
    """
    return letture.delete_by_ids(session, sorted(set(ids)))


def get_series(
    session, id_arnia: int, field: str, data_inizio, data_fine, limit: int
) -> list[dict[str, Any]]:
    """One measurement over time, for a chart."""
    data_inizio, data_fine = default_window(data_inizio, data_fine)
    return [
        dict(row)
        for row in letture.series(
            session, id_arnia, field, data_inizio, data_fine, limit
        )
    ]
