"""Tests for the MQTT handler's settings (mqtt_handler/config.py)."""

import pytest
from pydantic import ValidationError

from mqtt_handler.config import Settings, get_settings


@pytest.fixture(autouse=True)
def mqtt_env(monkeypatch):
    """
    No MQTT_* variable from the container, and an empty settings cache.

    The shared isolated_settings_env fixture strips the API's fields only.
    """
    for name in Settings.model_fields:
        if name.startswith("MQTT_"):
            monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_defaults_reach_a_local_broker_on_the_nodes_topic(required_env):
    """Unset, the handler subscribes to every node's data topic on localhost."""
    settings = Settings(_env_file=None)

    assert settings.MQTT_BROKER == "localhost"
    assert settings.MQTT_PORT == 1883
    assert settings.MQTT_TOPIC == "beehive/+/data"
    assert settings.MQTT_USER is None
    assert settings.MQTT_PASSWORD is None


def test_the_environment_configures_the_broker(monkeypatch, required_env):
    """Compose points the handler at the `mosquitto` service this way."""
    monkeypatch.setenv("MQTT_BROKER", "mosquitto")
    monkeypatch.setenv("MQTT_PORT", "8883")
    monkeypatch.setenv("MQTT_USER", "beehive")
    monkeypatch.setenv("MQTT_PASSWORD", "broker-secret")

    settings = Settings(_env_file=None)

    assert settings.MQTT_BROKER == "mosquitto"
    assert settings.MQTT_PORT == 8883
    assert settings.MQTT_USER == "beehive"
    assert settings.MQTT_PASSWORD.get_secret_value() == "broker-secret"


def test_the_broker_password_is_not_exposed_by_repr(monkeypatch, required_env):
    """A settings dump in a log or traceback must not reveal the broker password."""
    monkeypatch.setenv("MQTT_PASSWORD", "broker-secret")

    assert "broker-secret" not in repr(Settings(_env_file=None))


def test_the_database_password_is_still_required(monkeypatch, required_env):
    """
    The handler inherits CoreSettings, DB_PASSWORD included.

    It used to read it with a silent '' default; now a missing password stops
    the process at startup instead of at the first connection.
    """
    monkeypatch.delenv("DB_PASSWORD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_returns_a_cached_singleton(required_env):
    """The handler reads its settings once, at startup."""
    assert get_settings() is get_settings()
