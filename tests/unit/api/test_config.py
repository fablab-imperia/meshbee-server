"""Tests for the API settings (api/config.py).

The database half lives in meshbee_core and is covered by
tests/unit/core/test_config.py; what matters here is the API-only fields and
that subclassing really does carry the shared ones through.
"""

import pytest
from pydantic import ValidationError

from api.config import Settings, get_settings


def test_defaults_are_applied(build_settings):
    """Without any environment variable, the declared defaults are used."""
    settings = build_settings()

    assert settings.JWT_ALGORITHM == "HS256"
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert settings.CORS_ORIGINS == ["*"]


def test_the_shared_database_settings_are_inherited(build_settings):
    """
    Settings subclasses CoreSettings, so the API keeps one settings object.

    Asserted here because the split is invisible at the call site: `database.py`
    and every DB_* reference in the API rely on these fields still being present.
    """
    settings = build_settings()

    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.DB_NAME == "beehive_iot"
    assert settings.DB_USER == "beehive_user"
    assert settings.database_url.startswith("postgresql+psycopg2://")


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
    assert settings.JWT_SECRET_KEY.get_secret_value() == "s3cr3t-jwt"


def test_cors_origins_is_read_as_a_json_list(monkeypatch, required_env):
    """CORS_ORIGINS is a list field: the environment must carry a JSON array."""
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example", "https://b.example"]')

    assert Settings(_env_file=None).CORS_ORIGINS == [
        "https://a.example",
        "https://b.example",
    ]


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
