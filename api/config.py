"""Application configuration for the FastAPI entry point.

The database fields come from `meshbee_core.config.CoreSettings`; everything
below is API-only and is deliberately *not* shared with the MQTT handler, which
has no use for a JWT signing key.
"""

from functools import lru_cache

from pydantic import Field, SecretStr

from meshbee_core.config import CoreSettings


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


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (built once, then cached).

    Use as a FastAPI dependency when you need to override it in tests:
        def endpoint(config: Annotated[Settings, Depends(get_settings)]): ...
    """
    return Settings()


settings = get_settings()
