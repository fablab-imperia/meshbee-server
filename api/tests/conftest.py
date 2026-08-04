"""Shared fixtures for the API test-suite."""
import pytest

from config import Settings, get_settings

# The only settings without a default: every Settings instance needs them.
REQUIRED_ENV = {
    "DB_PASSWORD": "test-db-password",
    "JWT_SECRET_KEY": "test-jwt-secret",
}


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """
    Give every test a pristine environment and an empty settings cache.

    The api container is started by docker-compose with DB_HOST=postgres,
    DB_PASSWORD, JWT_SECRET_KEY... already exported, so without this the tests
    would assert against the compose values instead of the declared defaults.
    `get_settings` is lru_cached, so the cache is dropped on both sides of the
    test to keep results independent of execution order.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def required_env(monkeypatch):
    """Export only the settings that have no default."""
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    return dict(REQUIRED_ENV)


@pytest.fixture
def build_settings():
    """
    Build a Settings instance from explicit keyword arguments.

    `_env_file=None` disables the dotenv source: the result must not depend on
    whether a `.env` file happens to sit in the current working directory.
    """
    def _build(**overrides):
        return Settings(_env_file=None, **{**REQUIRED_ENV, **overrides})

    return _build
