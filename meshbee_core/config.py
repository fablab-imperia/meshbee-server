"""Configuration shared by every process that talks to the database.

Deliberately holds the DB fields only. Each entry point subclasses this and
adds what it alone needs — JWT and CORS for the API, broker coordinates for the
MQTT handler — so neither process is forced to carry a required setting it has
no use for. A required field added here must exist in the environment of
*every* service, so add sparingly.
"""
from functools import lru_cache
from urllib.parse import quote

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
        """Build the database URL.

        Nothing calls this today: `db.py` configures psycopg2's connection pool
        with discrete host/port/database/user/password arguments, never a DSN.
        It is kept because a DSN is what `create_engine()` takes, so this is the
        seam SQLAlchemy will plug into when it arrives.

        `quote`, not `quote_plus`: the latter is form encoding and renders a
        space as `+`, which every DSN parser (urllib, SQLAlchemy's make_url,
        libpq) reads back as a literal plus rather than a space. A credential
        containing a space would silently authenticate as the wrong user. The
        two agree on every other metacharacter.
        """
        user = quote(self.DB_USER, safe="")
        password = quote(self.DB_PASSWORD.get_secret_value(), safe="")
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache
def get_core_settings() -> CoreSettings:
    """Return the core settings singleton (built once, then cached)."""
    return CoreSettings()
