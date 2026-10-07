"""Tests for the letture repository (meshbee_core/repository/letture.py).

The INSERT here is the one both entry points reach, and `series` interpolates a
column name into its statement — the two things most worth pinning against a
real database.
"""

import pytest

from meshbee_core.repository import letture


def test_a_reading_is_stored_with_every_column_it_was_given(session, db, make_arnia):
    """The projection returned matches what was written."""
    arnia = make_arnia()

    row = letture.insert(
        session,
        id_arnia=arnia["id_arnia"],
        id_nodo=arnia["id_nodo"],
        timestamp=None,
        temperatura=34.5,
        umidita=65.0,
        peso=42.35,
        batteria=4.01,
        dati_raw={"rssi": -70},
    )

    assert row["id_arnia"] == arnia["id_arnia"]
    assert row["id_nodo"] == arnia["id_nodo"]
    assert float(row["temperatura"]) == 34.5
    assert float(row["umidita"]) == 65.0
    assert float(row["peso"]) == 42.35
    assert float(row["batteria"]) == 4.01
    assert row["dati_raw"] == {"rssi": -70}
    assert row["timestamp"] is not None


def test_an_absent_timestamp_defaults_to_now(session, db, make_arnia):
    """COALESCE(%s, CURRENT_TIMESTAMP) is what lets a node omit its clock."""
    arnia = make_arnia()

    row = letture.insert(
        session,
        id_arnia=arnia["id_arnia"],
        id_nodo=arnia["id_nodo"],
        timestamp=None,
        temperatura=20,
        umidita=None,
        peso=None,
        dati_raw=None,
    )

    assert row["timestamp"] is not None
    assert row["dati_raw"] is None


def test_an_unknown_arnia_is_refused_by_the_foreign_key(session, db, make_arnia):
    """The FK is what the API turns into a 404 instead of provisioning."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="letture_id_arnia_fkey"):
        letture.insert(
            session,
            id_arnia=999999,
            id_nodo="NODE-X",
            timestamp=None,
            temperatura=20,
            umidita=None,
            peso=None,
            dati_raw=None,
        )


# ============================================
# Chart series
# ============================================


@pytest.mark.parametrize("field", ["temperatura", "umidita", "peso", "batteria"])
def test_a_series_returns_only_the_timestamp_and_its_field(
    session, db, make_arnia, make_lettura, field
):
    """The series feeds a chart, so it carries nothing it does not need."""
    arnia = make_arnia()
    make_lettura(arnia, temperatura=20, umidita=50, peso=30, batteria=4)

    rows = letture.series(
        session, arnia["id_arnia"], field, "2000-01-01", "2100-01-01", 10
    )

    assert [set(row) for row in rows] == [{"timestamp", field}]


@pytest.mark.parametrize("field", ["temperatura", "umidita", "peso", "batteria"])
def test_a_series_skips_rows_where_its_field_is_null(
    session, db, make_arnia, make_lettura, field
):
    """
    A null measurement is not a data point.

    A node may report only some sensors, and plotting those as zeroes or gaps
    would misrepresent the hive.
    """
    arnia = make_arnia()
    make_lettura(arnia, temperatura=None, umidita=None, peso=None)
    # Inside every measurement's range, batteria's 0..5 V included.
    make_lettura(arnia, **{field: 4})

    rows = letture.series(
        session, arnia["id_arnia"], field, "2000-01-01", "2100-01-01", 10
    )

    assert len(rows) == 1
    assert float(rows[0][field]) == 4


def test_an_unknown_series_field_is_refused(session, db, make_arnia):
    """
    The whitelist is what keeps the interpolated column name safe.

    Callers pass a literal today, so reaching this is a programming error — but
    the statement is built by string formatting, so it is checked anyway.
    """
    arnia = make_arnia()

    with pytest.raises(ValueError, match="sconosciuto"):
        letture.series(
            session, arnia["id_arnia"], "password_hash", "2000-01-01", "2100-01-01", 10
        )


def test_readings_come_back_newest_first(session, db, make_arnia, make_lettura):
    """The mobile app shows the most recent reading first."""
    arnia = make_arnia()
    make_lettura(arnia, timestamp="2024-01-01 10:00", temperatura=1)
    make_lettura(arnia, timestamp="2024-06-01 10:00", temperatura=2)

    rows = letture.list_by_arnia(
        session, arnia["id_arnia"], "2000-01-01", "2100-01-01", 10
    )

    assert [float(r["temperatura"]) for r in rows] == [2, 1]


def test_readings_are_scoped_to_their_arnia(session, db, make_arnia, make_lettura):
    """Two hives on the same node must not see each other's readings."""
    first, second = make_arnia(), make_arnia()
    make_lettura(first, temperatura=1)
    make_lettura(second, temperatura=2)

    rows = letture.list_by_arnia(
        session, first["id_arnia"], "2000-01-01", "2100-01-01", 10
    )

    assert [float(r["temperatura"]) for r in rows] == [1]
