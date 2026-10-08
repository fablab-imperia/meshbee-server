"""Queries on `letture`."""

from typing import Any

from sqlmodel import Session, delete, select

from meshbee_core.models import Lettura
from meshbee_core.repository import as_dict, as_dicts, mapping

# The measurement columns exposed as chart series. A whitelist: `series` looks
# the column up by name.
SERIES_FIELDS = ("temperatura", "umidita", "peso", "batteria")


def insert(
    session: Session,
    *,
    id_arnia: int,
    id_nodo: str,
    timestamp,
    temperatura,
    umidita,
    peso,
    dati_raw: dict | None,
    batteria=None,
) -> dict[str, Any]:
    """
    Persist one reading. A null timestamp defaults to now, in the database.

    This is the single INSERT both entry points reach: the API's manual-insert
    endpoint and the MQTT ingest path.
    """
    lettura = Lettura(
        id_arnia=id_arnia,
        id_nodo=id_nodo,
        timestamp=timestamp,
        temperatura=temperatura,
        umidita=umidita,
        peso=peso,
        batteria=batteria,
        dati_raw=dati_raw or None,
    )
    session.add(lettura)
    session.flush()
    return as_dict(lettura)


def list_by_arnia(
    session: Session, id_arnia: int, data_inizio, data_fine, limit: int
) -> list[dict[str, Any]]:
    return as_dicts(
        session.exec(
            select(Lettura)
            .where(
                Lettura.id_arnia == id_arnia,
                Lettura.timestamp >= data_inizio,
                Lettura.timestamp <= data_fine,
            )
            .order_by(Lettura.timestamp.desc())
            .limit(limit)
        ).all()
    )


def list_all(session: Session, limit: int) -> list[dict[str, Any]]:
    return as_dicts(
        session.exec(
            select(Lettura).order_by(Lettura.timestamp.desc()).limit(limit)
        ).all()
    )


def get(session: Session, id_lettura: int) -> dict[str, Any] | None:
    return as_dict(session.get(Lettura, id_lettura))


def update(
    session: Session, id_lettura: int, changes: dict[str, Any]
) -> dict[str, Any] | None:
    """Set the given columns, None included; None if the reading does not exist."""
    lettura = session.get(Lettura, id_lettura)
    if lettura is None:
        return None
    for column, value in changes.items():
        setattr(lettura, column, value)
    session.flush()
    return as_dict(lettura)


def delete_by_ids(session: Session, ids: list[int]) -> int:
    """Delete the readings with these ids; returns how many there were."""
    result = session.exec(delete(Lettura).where(Lettura.id_lettura.in_(ids)))
    return result.rowcount


def series(
    session: Session, id_arnia: int, field: str, data_inizio, data_fine, limit: int
) -> list[dict[str, Any]]:
    """
    Timestamp plus one measurement, skipping rows where it is null.

    Rows with a null measurement are dropped rather than returned as gaps: the
    series feeds a chart, and a null point is not a data point.
    """
    if field not in SERIES_FIELDS:
        raise ValueError(f"Campo serie sconosciuto: {field!r}")
    column = getattr(Lettura, field)

    rows = session.exec(
        select(Lettura.timestamp, column)
        .where(
            Lettura.id_arnia == id_arnia,
            Lettura.timestamp.between(data_inizio, data_fine),
            column.is_not(None),
        )
        .order_by(Lettura.timestamp.desc())
        .limit(limit)
    ).all()
    return [mapping(row) for row in rows]
