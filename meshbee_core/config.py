"""Configuration shared by every process that talks to the database.

Deliberately holds the DB fields only. Each entry point subclasses this and
adds what it alone needs — JWT and CORS for the API, broker coordinates for the
MQTT handler — so neither process is forced to carry a required setting it has
no use for. A required field added here must exist in the environment of
*every* service, so add sparingly.
"""
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Database settings, common to the API and the MQTT handler."""

    # `.env` is only read when running outside Docker; in compose the values
    # are injected as plain environment variables, which always take priority.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "beehive_iot"
    DB_USER: str = "beehive_user"
    # No default: startup fails loudly instead of silently using an empty password.
    DB_PASSWORD: SecretStr = Field(description="PostgreSQL password (env: DB_PASSWORD)")

    @property
    def database_url(self) -> str:
        """Build the database URL"""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD.get_secret_value())
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache
def get_core_settings() -> CoreSettings:
    """Return the core settings singleton (built once, then cached)."""
    return CoreSettings()
