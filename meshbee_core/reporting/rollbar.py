"""Rollbar backend for error reporting (https://rollbar.com).

Registered as `rollbar` in the `meshbee.error_reporters` entry-point group;
needs the `rollbar` extra (`pip install -e ".[rollbar]"`). Selected with
ERROR_REPORTER=rollbar and a `post_server_item` token in ROLLBAR_ACCESS_TOKEN.

Uses the SDK's plain calls only, not `rollbar.contrib.fastapi`: that integration
sends the whole request (headers, query, client IP, optionally the body) and
reports 4xx too. Here a report carries the traceback and the context the
caller chose, already scrubbed, and a user id.

The SDK is configured against its defaults (pyrollbar 1.5.0), which are not
private enough for us: it would collect frame locals (route arguments hold
passwords and emails), capture the client IP, and call logging.basicConfig().
"""

from pathlib import Path

import rollbar
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from meshbee_core.reporting import SENSITIVE_KEYS

# Exact key names Rollbar replaces with asterisks, on top of its own defaults.
# A second line of defence: the context reaching `report` is already scrubbed.
EXTRA_SCRUB_FIELDS = [
    *SENSITIVE_KEYS,
    "access_token",
    "refresh_token",
    "jwt_secret_key",
    "db_password",
    "smtp_password",
    "mqtt_password",
    "rollbar_access_token",
]

# Rollbar's own list, taken before any init(): passing `scrub_fields` replaces it.
DEFAULT_SCRUB_FIELDS = list(rollbar.SETTINGS["scrub_fields"])

# The repository root, so Rollbar shows paths relative to it.
APP_ROOT = str(Path(__file__).resolve().parents[2])


class RollbarSettings(BaseSettings):
    """This backend's own settings, read only when it is the one selected."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    ROLLBAR_ACCESS_TOKEN: SecretStr

    @field_validator("ROLLBAR_ACCESS_TOKEN", mode="before")
    @classmethod
    def _not_empty(cls, value):
        # compose passes `${ROLLBAR_ACCESS_TOKEN:-}`: unset arrives as "".
        if not value:
            raise ValueError("ERROR_REPORTER=rollbar needs ROLLBAR_ACCESS_TOKEN")
        return value


class RollbarReporter:
    def __init__(self, service: str):
        self.service = service

    def report(self, exc, context, person_id) -> None:
        payload = {"context": context.get("route") or self.service}
        if person_id is not None:
            payload["person"] = {"id": person_id}
        rollbar.report_exc_info(
            (type(exc), exc, exc.__traceback__),
            request=None,
            extra_data={"service": self.service, **context},
            payload_data=payload,
        )

    def flush(self, timeout: float) -> None:
        # rollbar.wait() joins its sender threads; it takes no timeout, and each
        # send is bounded by the SDK's own HTTP timeout.
        rollbar.wait()


def build(
    *, environment: str, code_version: str | None, service: str, settings=None
) -> RollbarReporter:
    """Configure the SDK once for this process and return the reporter."""
    settings = settings or RollbarSettings()
    rollbar.init(
        settings.ROLLBAR_ACCESS_TOKEN.get_secret_value(),
        environment=environment,
        scrub_fields=list(dict.fromkeys([*DEFAULT_SCRUB_FIELDS, *EXTRA_SCRUB_FIELDS])),
        code_version=code_version,
        root=APP_ROOT,
        handler="thread",
        locals={"enabled": False},
        capture_ip=False,
        capture_email=False,
        capture_username=False,
        include_request_body=False,
        allow_logging_basic_config=False,
        suppress_reinit_warning=True,
    )
    return RollbarReporter(service)
