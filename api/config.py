"""Application configuration for the FastAPI entry point.

The database fields come from `meshbee_core.config.CoreSettings`; everything
below is API-only and is deliberately *not* shared with the MQTT handler, which
has no use for a JWT signing key (nor for the SMTP settings: only the API sends email).
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator

from meshbee_core.config import CoreSettings
from meshbee_core.mail import SmtpConfig, SmtpSecurity, default_port

# Optional settings that compose passes through as `${VAR:-}`: unset there means "".
EMPTY_MEANS_UNSET = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "MAIL_FROM",
    "PUBLIC_BASE_URL",
)


class Settings(CoreSettings):
    """Application settings"""

    # JWT
    JWT_SECRET_KEY: SecretStr = Field(
        description="JWT signing key, generate with: openssl rand -hex 32"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # API
    API_TITLE: str = "Meshbee API"
    # Bumped by release-please (release-please-config.json); don't edit by hand.
    API_VERSION: str = "1.2.0"  # x-release-please-version
    API_DESCRIPTION: str = "Meshbee API - Open beehive telemetry server API"

    # CORS — from the environment, pass a JSON list: CORS_ORIGINS=["https://example.org"]
    CORS_ORIGINS: list[str] = ["*"]

    # Outgoing email (SMTP). All optional: without SMTP_HOST, email is disabled.
    SMTP_HOST: str | None = None
    # Unset = the usual port for SMTP_SECURITY: 465 (ssl), 587 (starttls), 25 (none).
    SMTP_PORT: int | None = None
    SMTP_SECURITY: SmtpSecurity = "starttls"
    # Unset = no login, for relays that need none.
    SMTP_USER: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_TIMEOUT: float = Field(default=10.0, gt=0)
    # e.g. "Meshbee <noreply@example.org>", on a domain the provider has verified.
    MAIL_FROM: str | None = None
    # Where the app is reached, to build links in emails: https://meshbee.example.org
    PUBLIC_BASE_URL: str | None = None

    # Password reset by email (#54). Needs email and PUBLIC_BASE_URL; otherwise
    # the forgot route answers 503 and only an admin can set a new password.
    # A token's lifetime; at most a day, as a reset link has no reason to live longer.
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, gt=0, le=1440)
    # Reset emails one account can be sent per hour, whoever asks.
    PASSWORD_RESET_MAX_PER_ACCOUNT: int = Field(default=3, gt=0)
    # Reset requests one client address can make per hour, whatever the address
    # asked for. Counted in memory, per API process.
    PASSWORD_RESET_MAX_PER_IP: int = Field(default=10, gt=0)

    # Share requests (POST …/condivisioni) one user may make per hour, so sharing
    # cannot be used to try addresses in bulk (#40). In memory, per API process.
    SHARE_MAX_PER_HOUR: int = Field(default=30, gt=0)

    @field_validator(*EMPTY_MEANS_UNSET, mode="before")
    @classmethod
    def _empty_means_unset(cls, value):
        return None if value == "" else value

    @field_validator("PUBLIC_BASE_URL")
    @classmethod
    def _no_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @model_validator(mode="after")
    def _email_settings_are_complete(self):
        if self.SMTP_HOST and not self.MAIL_FROM:
            raise ValueError("SMTP_HOST is set but MAIL_FROM is not")
        if self.SMTP_USER and self.SMTP_PASSWORD is None:
            raise ValueError("SMTP_USER is set but SMTP_PASSWORD is not")
        return self

    @property
    def smtp_config(self) -> SmtpConfig | None:
        """How to send email, or None when it is disabled (no SMTP_HOST)."""
        if not self.SMTP_HOST:
            return None
        return SmtpConfig(
            host=self.SMTP_HOST,
            port=self.SMTP_PORT or default_port(self.SMTP_SECURITY),
            security=self.SMTP_SECURITY,
            sender=self.MAIL_FROM,
            username=self.SMTP_USER,
            password=(
                self.SMTP_PASSWORD.get_secret_value() if self.SMTP_PASSWORD else None
            ),
            timeout=self.SMTP_TIMEOUT,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (built once, then cached).

    Use as a FastAPI dependency when you need to override it in tests:
        def endpoint(config: Annotated[Settings, Depends(get_settings)]): ...
    """
    return Settings()


settings = get_settings()
