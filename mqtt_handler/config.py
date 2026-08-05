"""Configuration for the MQTT entry point.

The database fields come from `meshbee_core.config.CoreSettings`; everything
below is broker-specific and is not shared with the API.

Note DB_PASSWORD is now required, where this process used to read it with
`os.getenv('DB_PASSWORD', '')`. Compose already supplies it, so nothing changes
operationally — a missing password now fails at startup with a clear message
instead of at connect time with an authentication error.
"""
from functools import lru_cache
from typing import Optional

from pydantic import SecretStr

from meshbee_core.config import CoreSettings


class Settings(CoreSettings):
    """MQTT handler settings"""

    MQTT_BROKER: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_TOPIC: str = "beehive/+/data"
    MQTT_CLIENT_ID: str = "beehive-mqtt-handler"
    # Anonymous connection when unset; the broker in docker-compose does not
    # allow it, but a local broker might.
    MQTT_USER: Optional[str] = None
    MQTT_PASSWORD: Optional[SecretStr] = None


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (built once, then cached)."""
    return Settings()
