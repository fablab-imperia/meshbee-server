"""The /api/user/arnie/{id}/letture endpoints, including the four chart series."""

from datetime import datetime, timedelta

import pytest

NOW = datetime(2026, 6, 1, 12, 0, 0)

SERIES = [
    ("temperatura", "temperatura", "21.5"),
    ("umidita", "umidita", "55.0"),
    ("peso", "peso", "40.125"),
    ("batteria", "batteria", "4.01"),
]


@pytest.fixture
def arnia_con_letture(utente_con_arnia, make_lettura):
    """A readable arnia with three readings, one per hour, oldest first."""
    utente, arnia = utente_con_arnia("viewer")
    letture = [
        make_lettura(
            arnia,
            timestamp=NOW - timedelta(hours=h),
            temperatura=str(20 + h),
            umidita=str(50 + h),
            peso=str(40 + h),
            batteria=str(4 - h / 10),
        )
        for h in (2, 1, 0)
    ]
    return utente, arnia, letture


# ============================================
# GET .../letture
# ============================================


def test_letture_are_returned_newest_first(as_user, arnia_con_letture):
    """ORDER BY timestamp DESC — clients paginate from the most recent reading."""
    utente, arnia, _ = arnia_con_letture

    body = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/letture").json()

    timestamps = [row["timestamp"] for row in body]
    assert timestamps == sorted(timestamps, reverse=True)


def test_letture_carry_every_measurement_column(as_user, arnia_con_letture):
    """The SELECT lists columns by name; a rename would drop one of these."""
    utente, arnia, _ = arnia_con_letture

    row = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/letture").json()[0]

    assert set(row) == {
        "id_lettura",
        "id_arnia",
        "id_nodo",
        "timestamp",
        "temperatura",
        "umidita",
        "peso",
        "batteria",
        "dati_raw",
    }


def test_letture_are_scoped_to_the_requested_arnia(
    as_user, arnia_con_letture, make_arnia, make_lettura
):
    """Readings from another arnia never appear, even one the user can also read."""
    utente, arnia, _ = arnia_con_letture
    other = make_arnia(apiario=utente)
    make_lettura(other, temperatura="99")

    body = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/letture").json()

    assert {row["id_arnia"] for row in body} == {arnia["id_arnia"]}


def test_letture_respect_the_limit(as_user, arnia_con_letture):
    """LIMIT caps the result set."""
    utente, arnia, _ = arnia_con_letture

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture", params={"limit": 2})
        .json()
    )

    assert len(body) == 2


def test_letture_respect_the_date_window(as_user, arnia_con_letture):
    """data_inizio/data_fine filter on timestamp inclusively."""
    utente, arnia, _ = arnia_con_letture

    body = (
        as_user(utente)
        .get(
            f"/api/user/arnie/{arnia['id_arnia']}/letture",
            params={
                "data_inizio": (NOW - timedelta(hours=1)).isoformat(),
                "data_fine": NOW.isoformat(),
            },
        )
        .json()
    )

    assert len(body) == 2


def test_letture_default_to_the_last_year(as_user, utente_con_arnia, make_lettura):
    """With no window the endpoint looks back 365 days, so older rows drop out."""
    utente, arnia = utente_con_arnia("viewer")
    make_lettura(
        arnia, timestamp=datetime.now() - timedelta(days=400), temperatura="10"
    )
    make_lettura(arnia, temperatura="20")

    body = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/letture").json()

    assert len(body) == 1


@pytest.mark.parametrize("limit", [0, 10001])
def test_letture_reject_an_out_of_range_limit(as_user, utente_con_arnia, limit):
    """The Query bounds (1..10000) are enforced before the query runs."""
    utente, arnia = utente_con_arnia("viewer")

    response = as_user(utente).get(
        f"/api/user/arnie/{arnia['id_arnia']}/letture", params={"limit": limit}
    )

    assert response.status_code == 422


def test_letture_of_an_arnia_without_readings_is_empty(as_user, utente_con_arnia):
    """No readings is an empty list, not a 404."""
    utente, arnia = utente_con_arnia("viewer")

    response = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/letture")

    assert response.status_code == 200
    assert response.json() == []


# ============================================
# GET .../letture/{temperatura,umidita,peso,batteria}
# ============================================


@pytest.mark.parametrize("path, field, value", SERIES, ids=[s[0] for s in SERIES])
def test_series_return_only_timestamp_and_the_measurement(
    as_user, utente_con_arnia, make_lettura, path, field, value
):
    """The chart endpoints are deliberately narrow: two columns, nothing else."""
    utente, arnia = utente_con_arnia("viewer")
    make_lettura(arnia, **{field: value})

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture/{path}")
        .json()
    )

    assert set(body[0]) == {"timestamp", field}
    assert float(body[0][field]) == float(value)


@pytest.mark.parametrize("path, field, value", SERIES, ids=[s[0] for s in SERIES])
def test_series_skip_rows_where_the_measurement_is_null(
    as_user, utente_con_arnia, make_lettura, path, field, value
):
    """`AND <field> IS NOT NULL` keeps gaps out of the chart."""
    utente, arnia = utente_con_arnia("viewer")
    make_lettura(arnia, **{field: value})
    make_lettura(arnia)  # every measurement null

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture/{path}")
        .json()
    )

    assert len(body) == 1


@pytest.mark.parametrize("path, field, value", SERIES, ids=[s[0] for s in SERIES])
def test_series_are_newest_first(as_user, arnia_con_letture, path, field, value):
    """Same ordering as the raw readings endpoint."""
    utente, arnia, _ = arnia_con_letture

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture/{path}")
        .json()
    )

    timestamps = [row["timestamp"] for row in body]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.parametrize("path", ["temperatura", "umidita", "peso", "batteria"])
def test_series_respect_the_limit(as_user, arnia_con_letture, path):
    """LIMIT applies to the series endpoints too."""
    utente, arnia, _ = arnia_con_letture

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture/{path}", params={"limit": 2})
        .json()
    )

    assert len(body) == 2


@pytest.mark.parametrize("path", ["temperatura", "umidita", "peso", "batteria"])
def test_series_are_scoped_to_the_requested_arnia(
    as_user, arnia_con_letture, make_arnia, make_lettura, path
):
    """A second readable arnia does not bleed into the series."""
    utente, arnia, letture = arnia_con_letture
    other = make_arnia(apiario=utente)
    make_lettura(other, temperatura="99", umidita="99", peso="99", batteria="3")

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/letture/{path}")
        .json()
    )

    assert len(body) == len(letture)
