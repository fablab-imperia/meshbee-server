"""Tests for the application settings (api/config.py)."""
import pytest
from pydantic import ValidationError

from api.config import Settings, get_settings


def test_defaults_are_applied(build_settings):
    """Without any environment variable, the declared defaults are used."""
    settings = build_settings()

    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "beehive_iot"
    assert settings.DB_USER == "beehive_user"
    assert settings.JWT_ALGORITHM == "HS256"
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert settings.CORS_ORIGINS == ["*"]


def test_environment_overrides_defaults(monkeypatch, required_env):
    """Environment variables win over the defaults and are coerced to the field type."""
    monkeypatch.setenv("DB_HOST", "pg.example")
    monkeypatch.setenv("DB_PORT", "5544")

    settings = Settings(_env_file=None)

    assert settings.DB_HOST == "pg.example"
    assert settings.DB_PORT == 5544


@pytest.mark.parametrize("missing_field", ["DB_PASSWORD", "JWT_SECRET_KEY"])
def test_missing_secret_fails_loudly(monkeypatch, required_env, missing_field):
    """Secrets have no default on purpose: startup must fail, not run with an empty value."""
    monkeypatch.delenv(missing_field)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert (missing_field,) in [error["loc"] for error in exc_info.value.errors()]


def test_secrets_are_not_exposed_by_repr(build_settings):
    """A leaked settings dump (logs, tracebacks) must not reveal the secrets."""
    settings = build_settings(DB_PASSWORD="s3cr3t-db", JWT_SECRET_KEY="s3cr3t-jwt")

    assert "s3cr3t-db" not in repr(settings)
    assert "s3cr3t-jwt" not in repr(settings)
    assert settings.DB_PASSWORD.get_secret_value() == "s3cr3t-db"


def test_database_url_is_built_from_the_db_settings(build_settings):
    """database_url assembles the psycopg2 DSN from the single DB_* settings."""
    settings = build_settings(
        DB_HOST="db.local",
        DB_PORT=6543,
        DB_NAME="apiario",
        DB_USER="beehive_user",
        DB_PASSWORD="pw",
    )

    assert settings.database_url == "postgresql://beehive_user:pw@db.local:6543/apiario"


def test_database_url_escapes_special_characters(build_settings):
    """Credentials containing URL metacharacters must not corrupt the DSN."""
    settings = build_settings(
        DB_HOST="db.local",
        DB_PORT=6543,
        DB_NAME="apiario",
        DB_USER="beehive user",
        DB_PASSWORD="p@ss:w/rd#1",
    )

    assert settings.database_url == (
        "postgresql://beehive+user:p%40ss%3Aw%2Frd%231@db.local:6543/apiario"
    )


def test_cors_origins_is_read_as_a_json_list(monkeypatch, required_env):
    """CORS_ORIGINS is a list field: the environment must carry a JSON array."""
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example", "https://b.example"]')

    assert Settings(_env_file=None).CORS_ORIGINS == ["https://a.example", "https://b.example"]


def test_environment_lookup_is_case_sensitive(monkeypatch, required_env):
    """case_sensitive=True: a lowercase variable is not picked up."""
    monkeypatch.setenv("db_name", "lowercase_db")

    assert Settings(_env_file=None).DB_NAME == "beehive_iot"


def test_unrelated_environment_variables_are_ignored(monkeypatch, required_env):
    """extra="ignore": the seed/mqtt variables sharing the environment must not break Settings."""
    monkeypatch.setenv("ADMIN_PASSWORD", "whatever")
    monkeypatch.setenv("MQTT_BROKER", "mosquitto")

    settings = Settings(_env_file=None)

    assert settings.DB_NAME == "beehive_iot"
    assert not hasattr(settings, "ADMIN_PASSWORD")


def test_get_settings_returns_a_cached_singleton(required_env):
    """get_settings is lru_cached: same object every call, until the cache is cleared."""
    first = get_settings()

    assert get_settings() is first
    assert first.DB_PASSWORD.get_secret_value() == "test-db-password"

    get_settings.cache_clear()
    assert get_settings() is not first
