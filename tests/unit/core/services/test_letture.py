"""Tests for the readings service (meshbee_core/services/letture.py)."""

from datetime import datetime, timedelta

import pytest

from meshbee_core.errors import InvalidData
from meshbee_core.models import LetturaCreate
from meshbee_core.services import letture

VALID = {"id_arnia": 1, "id_nodo": "NODE001"}


# ============================================
# Validation on the way in
# ============================================

OUT_OF_RANGE = [
    ("temperatura", -50.01),
    ("temperatura", 100.01),
    ("umidita", -0.01),
    ("umidita", 100.01),
    ("peso", -0.01),
    ("batteria", -0.01),
    ("batteria", 5.01),
]


@pytest.mark.parametrize(
    "field, value", OUT_OF_RANGE, ids=[f"{f}={v}" for f, v in OUT_OF_RANGE]
)
def test_an_out_of_range_measurement_is_refused(fake_session, field, value):
    """
    The service refuses what the schema's CHECK constraints would refuse.

    This is the behaviour the ingest path gained: it used to send the value to
    Postgres, which rejected it, and the reading was logged and lost.
    """
    session = fake_session()

    with pytest.raises(InvalidData):
        letture.record_reading(session, {**VALID, field: value})

    assert session.added == [], "nessuna INSERT deve essere tentata"


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperatura", -50),
        ("temperatura", 100),
        ("umidita", 0),
        ("umidita", 100),
        ("peso", 0),
        ("batteria", 0),
        ("batteria", 5),
    ],
)
def test_the_inclusive_boundary_is_accepted(fake_session, field, value):
    """The bounds are inclusive on both sides, matching the CHECK constraints."""
    session = fake_session()

    letture.record_reading(session, {**VALID, field: value})

    assert len(session.added) == 1


def test_a_missing_measurement_is_allowed(fake_session):
    """A node reporting only some sensors still gets its reading stored."""
    session = fake_session()

    letture.record_reading(session, {**VALID, "temperatura": 20})

    [lettura] = session.added
    assert lettura.temperatura == 20
    assert lettura.umidita is None and lettura.peso is None, (
        "le misure assenti arrivano come NULL"
    )


def test_an_already_validated_model_is_not_revalidated(fake_session):
    """
    The API hands over a model FastAPI already built, and it passes straight through.

    Re-running validation would be harmless but rebuilding the model would not:
    it is what keeps the API's responses byte-identical to before the refactor.
    """
    session = fake_session()
    lettura = LetturaCreate(**VALID, temperatura=21)

    letture.record_reading(session, lettura)

    assert len(session.added) == 1


def test_a_payload_missing_required_fields_is_refused(fake_session):
    """id_arnia and id_nodo have no defaults: a truncated payload cannot be stored."""
    session = fake_session()

    with pytest.raises(InvalidData):
        letture.record_reading(session, {"temperatura": 20})

    assert session.added == []


# ============================================
# Date windows
# ============================================


def test_an_open_window_defaults_to_the_last_year():
    """Both list endpoints and all three chart series share this default."""
    before = datetime.now()

    data_inizio, data_fine = letture.default_window(None, None)

    assert data_fine >= before
    assert timedelta(days=364) < (data_fine - data_inizio) < timedelta(days=366)


def test_explicit_window_bounds_are_left_alone():
    """A caller that names both ends gets exactly those."""
    inizio, fine = datetime(2024, 1, 1), datetime(2024, 6, 30)

    assert letture.default_window(inizio, fine) == (inizio, fine)


def test_only_the_missing_end_is_filled_in():
    """Half-open ranges are the common case from the mobile app."""
    inizio = datetime(2024, 1, 1)

    filled_inizio, filled_fine = letture.default_window(inizio, None)

    assert filled_inizio == inizio
    assert filled_fine > inizio
