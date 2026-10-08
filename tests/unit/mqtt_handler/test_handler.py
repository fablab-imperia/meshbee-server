"""Tests for the MQTT callback (mqtt_handler/handler.py).

What the callback owns is failure handling: a bad message must not kill the
subscriber, because paho would keep delivering to a handler that has stopped
working. The happy path is covered end-to-end in
tests/integration/test_ingest_parity.py.
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from mqtt_handler import handler as mqtt_handler

TOPIC = "beehive/NODE001/data"


def message(payload, topic=TOPIC):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return SimpleNamespace(topic=topic, payload=raw)


@pytest.fixture
def session_calls(monkeypatch):
    """Record whether the callback reached the database, without providing one."""
    opened = []

    @contextmanager
    def _session():
        opened.append(True)
        raise AssertionError("il messaggio non doveva raggiungere il database")
        yield  # pragma: no cover

    monkeypatch.setattr(mqtt_handler, "get_session", _session)
    return opened


def deliver(msg):
    """Invoke the real callback unbound, so no broker connection is needed."""
    mqtt_handler.BeehiveMQTTHandler.on_message(None, None, None, msg)


def test_malformed_json_never_reaches_the_database(session_calls):
    """Parsing failures are answered before a connection is taken from the pool."""
    deliver(message(b"{not json"))

    assert session_calls == []


def test_a_message_without_a_node_never_reaches_the_database(session_calls):
    """Nothing can be attributed, so nothing is written."""
    deliver(message({"temperatura": 20}, topic="beehive"))

    assert session_calls == []


def test_a_database_failure_does_not_propagate(monkeypatch):
    """
    An outage must not escape the callback.

    paho swallows exceptions from on_message inconsistently across versions; a
    handler that raises risks a subscriber that is up but no longer storing
    anything.
    """

    @contextmanager
    def _broken_session():
        raise RuntimeError("database non raggiungibile")
        yield  # pragma: no cover

    monkeypatch.setattr(mqtt_handler, "get_session", _broken_session)

    deliver(message({"id_sensore": "SENSOR01", "temperatura": 20}))


def test_a_rejected_reading_does_not_propagate(monkeypatch, caplog):
    """A CoreError is reported and dropped, not raised at paho."""
    from meshbee_core.errors import InvalidData

    @contextmanager
    def _session():
        yield object()

    def _reject(session, payload):
        raise InvalidData("Temperatura deve essere tra -50 e 100°C")

    monkeypatch.setattr(mqtt_handler, "get_session", _session)
    monkeypatch.setattr(mqtt_handler.ingest, "record_node_reading", _reject)

    deliver(message({"id_sensore": "SENSOR01", "temperatura": 500}))

    assert "Temperatura deve essere tra -50 e 100" in caplog.text


def test_a_stored_reading_is_logged_with_its_measurements(monkeypatch, caplog):
    """The success line is how an operator confirms a node is reporting."""
    import logging

    @contextmanager
    def _session():
        yield object()

    def _store(session, payload):
        return {
            "id_arnia": 7,
            "id_nodo": "NODE001",
            "temperatura": 34.5,
            "umidita": 65.0,
            "peso": 42.35,
            "batteria": 4.01,
        }

    monkeypatch.setattr(mqtt_handler, "get_session", _session)
    monkeypatch.setattr(mqtt_handler.ingest, "record_node_reading", _store)

    with caplog.at_level(logging.INFO):
        deliver(message({"id_sensore": "SENSOR01", "temperatura": 34.5}))

    assert "Salvata lettura per arnia 7" in caplog.text
    assert "34.5" in caplog.text
    assert "B: 4.01V" in caplog.text


SETTINGS = SimpleNamespace(
    MQTT_CLIENT_ID="test-handler",
    MQTT_BROKER="broker",
    MQTT_PORT=1883,
    MQTT_TOPIC="beehive/+/data",
)


def connack(name):
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.reasoncodes import ReasonCode

    return ReasonCode(PacketTypes.CONNACK, name)


def test_the_handler_builds_a_paho_client():
    """
    paho-mqtt 2 refuses a Client without a callback API version.

    Constructing it needs no broker, so this catches the crash-on-start that a
    paho upgrade would otherwise only show in the running container.
    """
    handler = mqtt_handler.BeehiveMQTTHandler(SETTINGS)

    assert handler.client.on_connect == handler.on_connect


@pytest.mark.parametrize(
    ("reason", "subscribed"),
    [("Success", ["beehive/+/data"]), ("Not authorized", [])],
)
def test_on_connect_subscribes_only_on_success(reason, subscribed):
    handler = mqtt_handler.BeehiveMQTTHandler(SETTINGS)
    topics = []
    client = SimpleNamespace(subscribe=topics.append)

    handler.on_connect(client, None, None, connack(reason), None)

    assert topics == subscribed
