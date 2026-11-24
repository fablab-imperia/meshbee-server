"""Configuration shared by every process that talks to the database.

Deliberately holds the DB fields only, plus the error-reporting switch (every
process reports). Each entry point subclasses this and
adds what it alone needs — JWT and CORS for the API, broker coordinates for the
MQTT handler — so neither process is forced to carry a required setting it has
no use for. A required field added here must exist in the environment of
*every* service, so add sparingly.
"""

from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Database and error-reporting settings, common to every process."""

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

    # Error reporting (#56), see meshbee_core/reporting. Every process reports,
    # so it lives here; all optional. The switch is separate from the provider,
    # so an environment can keep the provider configured and still send nothing.
    # On without ERROR_REPORTER still sends nothing (production turns the switch
    # on by default, before anyone has picked a provider).
    ERROR_REPORTING_ENABLED: bool = False
    # A backend name in the `meshbee.error_reporters` entry-point group, e.g. "rollbar".
    ERROR_REPORTER: str | None = None
    # The label each report carries: production, development, staging…
    ERROR_REPORTER_ENVIRONMENT: str = "development"

    @field_validator("ERROR_REPORTER", mode="before")
    @classmethod
    def _empty_means_unset(cls, value):
        # compose passes `${ERROR_REPORTER:-}`: unset arrives as "".
        return None if value == "" else value

    @property
    def database_url(self) -> str:
        """Build the database URL.

        What `db.init_db_pool` hands to `create_engine()`, and what the
        migrations connect with. The driver is named, `postgresql+psycopg://`
        (psycopg 3), so the URL does not depend on SQLAlchemy's default.

        `quote`, not `quote_plus`: the latter is form encoding and renders a
        space as `+`, which every DSN parser (urllib, SQLAlchemy's make_url,
        libpq) reads back as a literal plus rather than a space. A credential
        containing a space would silently authenticate as the wrong user. The
        two agree on every other metacharacter.
        """
        user = quote(self.DB_USER, safe="")
        password = quote(self.DB_PASSWORD.get_secret_value(), safe="")
        return f"postgresql+psycopg://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache
def get_core_settings() -> CoreSettings:
    """Return the core settings singleton (built once, then cached)."""
    return CoreSettings()
