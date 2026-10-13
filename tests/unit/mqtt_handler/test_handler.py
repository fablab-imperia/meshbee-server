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


def disconnect(name):
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.reasoncodes import ReasonCode

    return ReasonCode(PacketTypes.DISCONNECT, name)


@pytest.mark.parametrize(
    ("reason", "warned"),
    [("Normal disconnection", False), ("Unspecified error", True)],
)
def test_only_an_unexpected_disconnect_is_reported(caplog, reason, warned):
    """Our own stop() disconnects cleanly; only a dropped link deserves a warning."""
    handler = mqtt_handler.BeehiveMQTTHandler(SETTINGS)

    handler.on_disconnect(None, None, None, disconnect(reason), None)

    assert ("Disconnessione inaspettata" in caplog.text) is warned


# ============================================
# Lifecycle: run, stop, signals, main
# ============================================


class FakeClient:
    """A paho client that records calls instead of opening a socket."""

    def __init__(self, connect_error=None):
        self.calls = []
        self.connect_error = connect_error

    def username_pw_set(self, user, password):
        self.calls.append(("username_pw_set", user, password))

    def connect(self, host, port, keepalive):
        self.calls.append(("connect", host, port, keepalive))
        if self.connect_error:
            raise self.connect_error

    def loop_start(self):
        self.calls.append(("loop_start",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))


def broker_settings(user=None, password=None):
    from pydantic import SecretStr

    return SimpleNamespace(
        **vars(SETTINGS),
        MQTT_USER=user,
        MQTT_PASSWORD=SecretStr(password) if password else None,
    )


def running_handler(monkeypatch, settings, client=None):
    """A handler on a fake client whose wait loop ends after one turn."""
    handler = mqtt_handler.BeehiveMQTTHandler(settings)
    handler.client = client or FakeClient()

    def one_turn(seconds):
        handler.running = False

    monkeypatch.setattr(mqtt_handler.time, "sleep", one_turn)
    return handler


def test_run_authenticates_when_credentials_are_set(monkeypatch):
    """The compose broker refuses anonymous clients; the password must reach paho."""
    handler = running_handler(monkeypatch, broker_settings("beehive", "s3cret"))

    handler.run()

    assert handler.client.calls[:3] == [
        ("username_pw_set", "beehive", "s3cret"),
        ("connect", "broker", 1883, 60),
        ("loop_start",),
    ]


@pytest.mark.parametrize(
    ("user", "password"), [(None, None), ("beehive", None), (None, "s3cret")]
)
def test_run_connects_anonymously_without_a_full_credential_pair(
    monkeypatch, user, password
):
    """Half a credential is not sent: a local broker may allow anonymous clients."""
    handler = running_handler(monkeypatch, broker_settings(user, password))

    handler.run()

    assert handler.client.calls[0] == ("connect", "broker", 1883, 60)


def test_the_broker_password_never_reaches_the_log(monkeypatch, caplog):
    """The user name is logged to help an operator; the password must not be."""
    import logging

    handler = running_handler(monkeypatch, broker_settings("beehive", "s3cret"))

    with caplog.at_level(logging.INFO):
        handler.run()

    assert "beehive" in caplog.text
    assert "s3cret" not in caplog.text


def test_run_stops_the_client_when_its_loop_ends(monkeypatch):
    """Leaving run() must always release the network loop and the connection."""
    handler = running_handler(monkeypatch, broker_settings())

    handler.run()

    assert handler.client.calls[-2:] == [("loop_stop",), ("disconnect",)]
    assert handler.running is False


@pytest.mark.parametrize(
    "error", [ConnectionRefusedError("broker non raggiungibile"), KeyboardInterrupt()]
)
def test_run_stops_cleanly_when_it_fails_or_is_interrupted(monkeypatch, caplog, error):
    """
    An unreachable broker or Ctrl-C ends run() without a traceback at main().

    main() still closes the pool in its finally, and the container restart
    policy brings the handler back once the broker is up.
    """
    handler = running_handler(
        monkeypatch, broker_settings(), FakeClient(connect_error=error)
    )

    handler.run()

    assert handler.client.calls[-2:] == [("loop_stop",), ("disconnect",)]


def test_a_termination_signal_exits_cleanly():
    """
    `docker stop` sends SIGTERM; exiting with SystemExit(0) runs main()'s finally.

    That is what closes the database pool instead of leaving connections
    for Postgres to time out.
    """
    with pytest.raises(SystemExit) as exc_info:
        mqtt_handler.signal_handler(15, None)

    assert exc_info.value.code == 0


@pytest.fixture
def main_env(monkeypatch):
    """main() with its collaborators recorded: signals, settings, pool, handler."""
    events = []
    signals = {}
    settings = SimpleNamespace(DB_HOST="db", DB_PORT=5432, DB_NAME="beehive_test")

    class FakeHandler:
        run_error = None

        def __init__(self, given):
            assert given is settings
            events.append("handler")

        def run(self):
            events.append("run")
            if FakeHandler.run_error:
                raise FakeHandler.run_error

    monkeypatch.setattr(mqtt_handler.signal, "signal", signals.__setitem__)
    monkeypatch.setattr(mqtt_handler, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mqtt_handler,
        "init_db_pool",
        lambda s, maxconn: events.append(("init_db_pool", maxconn)),
    )
    monkeypatch.setattr(mqtt_handler, "close_db_pool", lambda: events.append("close"))
    monkeypatch.setattr(mqtt_handler, "BeehiveMQTTHandler", FakeHandler)
    return SimpleNamespace(events=events, signals=signals, handler=FakeHandler)


def test_main_opens_the_pool_runs_and_closes_it(main_env):
    """The pool is sized for this process, and released when the handler returns."""
    mqtt_handler.main()

    assert main_env.events == [
        ("init_db_pool", mqtt_handler.DB_POOL_SIZE),
        "handler",
        "run",
        "close",
    ]


def test_main_handles_both_termination_signals(main_env):
    """Ctrl-C locally and SIGTERM from Docker must both take the clean exit."""
    import signal

    mqtt_handler.main()

    assert main_env.signals == {
        signal.SIGINT: mqtt_handler.signal_handler,
        signal.SIGTERM: mqtt_handler.signal_handler,
    }


def test_main_closes_the_pool_even_when_the_handler_fails(main_env):
    """A crash in the handler must not leave pooled connections open."""
    main_env.handler.run_error = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        mqtt_handler.main()

    assert main_env.events[-1] == "close"


def test_main_exits_without_a_database_before_touching_the_broker(
    main_env, monkeypatch
):
    """
    No database, no handler: exit 1 so the container restarts.

    Subscribing without somewhere to store readings would acknowledge messages
    and lose them.
    """

    def unreachable(settings, maxconn):
        raise RuntimeError("database non raggiungibile")

    monkeypatch.setattr(mqtt_handler, "init_db_pool", unreachable)

    with pytest.raises(SystemExit) as exc_info:
        mqtt_handler.main()

    assert exc_info.value.code == 1
    assert "handler" not in main_env.events
