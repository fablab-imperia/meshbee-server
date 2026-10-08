"""Tests for the shared database settings (meshbee_core/config.py)."""

from urllib.parse import unquote, urlsplit

import pytest
from pydantic import ValidationError

from meshbee_core.config import CoreSettings, get_core_settings


def test_defaults_are_applied(build_core_settings):
    """Without any environment variable, the declared defaults are used."""
    settings = build_core_settings()

    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "beehive_iot"
    assert settings.DB_USER == "beehive_user"


def test_environment_overrides_defaults(monkeypatch, required_env):
    """Environment variables win over the defaults and are coerced to the field type."""
    monkeypatch.setenv("DB_HOST", "pg.example")
    monkeypatch.setenv("DB_PORT", "5544")

    settings = CoreSettings(_env_file=None)

    assert settings.DB_HOST == "pg.example"
    assert settings.DB_PORT == 5544


def test_a_missing_db_password_fails_loudly(monkeypatch, required_env):
    """
    DB_PASSWORD has no default on purpose.

    The MQTT handler used to read it with `os.getenv('DB_PASSWORD', '')`, so a
    missing password produced a confusing authentication error at connect time
    instead of a clear failure at startup.
    """
    monkeypatch.delenv("DB_PASSWORD")

    with pytest.raises(ValidationError) as exc_info:
        CoreSettings(_env_file=None)

    assert ("DB_PASSWORD",) in [error["loc"] for error in exc_info.value.errors()]


def test_the_db_password_is_not_exposed_by_repr(build_core_settings):
    """A leaked settings dump (logs, tracebacks) must not reveal the password."""
    settings = build_core_settings(DB_PASSWORD="s3cr3t-db")

    assert "s3cr3t-db" not in repr(settings)
    assert settings.DB_PASSWORD.get_secret_value() == "s3cr3t-db"


def test_database_url_is_built_from_the_db_settings(build_core_settings):
    """database_url assembles the psycopg2 DSN from the single DB_* settings."""
    settings = build_core_settings(
        DB_HOST="db.local",
        DB_PORT=6543,
        DB_NAME="apiario",
        DB_USER="beehive_user",
        DB_PASSWORD="pw",
    )

    assert (
        settings.database_url
        == "postgresql+psycopg2://beehive_user:pw@db.local:6543/apiario"
    )


def test_database_url_escapes_special_characters(build_core_settings):
    """Credentials containing URL metacharacters must not corrupt the DSN."""
    settings = build_core_settings(
        DB_HOST="db.local",
        DB_PORT=6543,
        DB_NAME="apiario",
        DB_USER="beehive user",
        DB_PASSWORD="p@ss:w/rd#1",
    )

    assert settings.database_url == (
        "postgresql+psycopg2://beehive%20user:p%40ss%3Aw%2Frd%231@db.local:6543/apiario"
    )


@pytest.mark.parametrize(
    "credential", ["beehive user", "p@ss:w/rd#1", "pa+ss", "a b+c%d"]
)
def test_credentials_survive_the_round_trip_through_the_dsn(
    build_core_settings, credential
):
    """
    What a DSN parser reads back must be the credential we were given.

    Asserted as a round-trip rather than a fixed string because the failure this
    guards is subtle: `quote_plus` renders a space as `+`, and unquoting gives
    back a literal plus, so a password with a space would authenticate as
    something else. Nothing calls database_url yet, so only a test can catch it
    before SQLAlchemy makes it load-bearing.
    """
    settings = build_core_settings(DB_USER=credential, DB_PASSWORD=credential)

    parsed = urlsplit(settings.database_url)

    assert unquote(parsed.username) == credential
    assert unquote(parsed.password) == credential


def test_environment_lookup_is_case_sensitive(monkeypatch, required_env):
    """case_sensitive=True: a lowercase variable is not picked up."""
    monkeypatch.setenv("db_name", "lowercase_db")

    assert CoreSettings(_env_file=None).DB_NAME == "beehive_iot"


def test_the_api_only_settings_are_ignored_here(monkeypatch, required_env):
    """
    extra="ignore" is what lets one environment serve both processes.

    The api and seed containers export JWT_SECRET_KEY alongside the database
    variables; CoreSettings must tolerate it rather than reject the environment.
    """
    monkeypatch.setenv("ADMIN_PASSWORD", "whatever")
    monkeypatch.setenv("MQTT_BROKER", "mosquitto")

    settings = CoreSettings(_env_file=None)

    assert settings.DB_NAME == "beehive_iot"
    assert not hasattr(settings, "JWT_SECRET_KEY")
    assert not hasattr(settings, "ADMIN_PASSWORD")


def test_get_core_settings_returns_a_cached_singleton(required_env):
    """get_core_settings is lru_cached: same object every call, until cleared."""
    first = get_core_settings()

    assert get_core_settings() is first
    assert first.DB_PASSWORD.get_secret_value() == "test-db-password"

    get_core_settings.cache_clear()
    assert get_core_settings() is not first
