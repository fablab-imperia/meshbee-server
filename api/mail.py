"""Email from the API: which mailer to use, and sending it off the request path.

The mailer itself is `meshbee_core.mail`; this module only connects it to the
API's settings and to FastAPI's `BackgroundTasks`, so a slow or broken SMTP
server never holds up a response.
"""

import logging
from typing import Annotated

from fastapi import BackgroundTasks, Depends

from api.config import Settings, get_settings
from meshbee_core.errors import Unavailable
from meshbee_core.mail import Mailer

logger = logging.getLogger(__name__)


def get_mailer(config: Annotated[Settings, Depends(get_settings)]) -> Mailer | None:
    """The configured mailer, or None when email is disabled (no SMTP_HOST).

    A route dependency, so tests swap in a fake through `dependency_overrides`.
    """
    smtp = config.smtp_config
    return Mailer(smtp) if smtp else None


def _send_logging_failures(
    mailer: Mailer, to: str, subject: str, text: str, html: str | None
) -> None:
    try:
        mailer.send(to, subject, text, html)
    except Unavailable:
        # The response has already gone out, so there is no one left to tell but
        # the log. The mailer logged the server's reply; this says what was lost.
        logger.warning(f"Email '{subject}' to {to} was not sent")


def send_later(
    background_tasks: BackgroundTasks,
    mailer: Mailer,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
) -> None:
    """Queue one message to go out after the response, logging (not raising) a failure."""
    background_tasks.add_task(_send_logging_failures, mailer, to, subject, text, html)
