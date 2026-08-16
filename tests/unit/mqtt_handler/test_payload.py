"""Tests for MQTT payload decoding (mqtt_handler/payload.py).

The handler had no tests at all before the refactor, and this is the layer that
faces the firmware: whatever an ESP32 puts on the wire arrives here first.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from mqtt_handler.payload import parse_message, parse_timestamp

TOPIC = "beehive/NODE001/data"


def encode(payload):
    return json.dumps(payload).encode("utf-8")


# ============================================
# Identifying the node
# ============================================


def test_the_node_id_is_taken_from_the_topic_when_absent_from_the_body():
    """Firmware may rely on the topic alone: `beehive/<id_nodo>/data`."""
    parsed = parse_message(TOPIC, encode({"temperatura": 20}))

    assert parsed["id_nodo"] == "NODE001"


def test_the_body_wins_over_the_topic():
    """An explicit id_nodo is authoritative, matching the pre-refactor behaviour."""
    parsed = parse_message(TOPIC, encode({"id_nodo": "NODE-EXPLICIT"}))

    assert parsed["id_nodo"] == "NODE-EXPLICIT"


def test_a_message_with_no_identifiable_node_is_refused():
    """Without a node there is nothing to attribute the reading to."""
    with pytest.raises(ValueError, match="id_nodo"):
        parse_message("beehive", encode({"temperatura": 20}))


# ============================================
# Malformed input
# ============================================


def test_malformed_json_is_refused():
    """A truncated or corrupted publish must not take the handler down."""
    with pytest.raises(ValueError, match="JSON"):
        parse_message(TOPIC, b"{not json")


def test_a_non_object_payload_is_refused():
    """Valid JSON that is not an object has no fields to read."""
    with pytest.raises(ValueError):
        parse_message(TOPIC, b"[1, 2, 3]")


def test_undecodable_bytes_are_refused():
    """A garbled transmission is a ValueError like any other bad payload."""
    with pytest.raises(ValueError):
        parse_message(TOPIC, b"\xff\xfe\x00")


# ============================================
# Timestamps
# ============================================


def test_a_zulu_timestamp_is_understood():
    """
    The firmware sends the Zulu suffix.

    `datetime.fromisoformat` did not accept 'Z' before Python 3.11, so the
    replacement is load-bearing on the interpreter this runs on today.
    """
    parsed = parse_timestamp("2024-02-01T12:00:00Z")

    assert parsed == datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)


def test_an_offset_timestamp_is_understood():
    """Nodes configured to a local zone report an explicit offset."""
    parsed = parse_timestamp("2024-02-01T12:00:00+02:00")

    assert parsed == datetime(2024, 2, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))


def test_an_unparseable_timestamp_falls_back_to_now():
    """
    A node with a broken clock still gets its measurement stored.

    None means "use CURRENT_TIMESTAMP" downstream. Rejecting the reading would
    lose real sensor data over a formatting problem.
    """
    assert parse_timestamp("yesterday-ish") is None


def test_an_absent_timestamp_falls_back_to_now():
    assert parse_timestamp(None) is None


def test_the_measurements_are_passed_through_untouched():
    """Parsing does not validate ranges — that is the service's job."""
    parsed = parse_message(TOPIC, encode({
        "id_sensore": "SENSOR01",
        "temperatura": 34.5,
        "umidita": 65.0,
        "peso": 42.35,
        "dati_raw": {"rssi": -70},
    }))

    assert parsed["id_sensore"] == "SENSOR01"
    assert parsed["temperatura"] == 34.5
    assert parsed["umidita"] == 65.0
    assert parsed["peso"] == 42.35
    assert parsed["dati_raw"] == {"rssi": -70}


def test_an_out_of_range_measurement_still_parses():
    """
    Parsing and validating are separate steps on purpose.

    The service decides what is acceptable; keeping that out of here means the
    two entry points cannot disagree about it.
    """
    parsed = parse_message(TOPIC, encode({"temperatura": 500}))

    assert parsed["temperatura"] == 500
