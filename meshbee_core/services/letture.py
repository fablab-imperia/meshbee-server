"""Readings: recording them, and reading them back as lists or chart series."""

from datetime import datetime, timedelta
from typing import Any

from meshbee_core.db import integrity_errors
from meshbee_core.errors import InvalidData, NotFound
from meshbee_core.models import LetturaCreate
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
    session, id_arnia: int, data_inizio, data_fine, limit: int
) -> list[dict[str, Any]]:
    data_inizio, data_fine = default_window(data_inizio, data_fine)
    return [
        dict(row)
        for row in letture.list_by_arnia(
            session, id_arnia, data_inizio, data_fine, limit
        )
    ]


def list_all(session, limit: int) -> list[dict[str, Any]]:
    return [dict(row) for row in letture.list_all(session, limit)]


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
