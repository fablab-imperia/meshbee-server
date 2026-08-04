"""
Application configuration
"""
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings"""

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

    # JWT
    JWT_SECRET_KEY: SecretStr = Field(
        description="JWT signing key, generate with: openssl rand -hex 32"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # API
    API_TITLE: str = "Beehive IoT API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "API per gestione sistema IoT arnie"

    # CORS — from the environment, pass a JSON list: CORS_ORIGINS=["https://example.org"]
    CORS_ORIGINS: list[str] = ["*"]

    @property
    def database_url(self) -> str:
        """Build the database URL"""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD.get_secret_value())
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (built once, then cached).

    Use as a FastAPI dependency when you need to override it in tests:
        def endpoint(config: Annotated[Settings, Depends(get_settings)]): ...
    """
    return Settings()


settings = get_settings()
