"""Email for the API tests: a fake mailer, and settings that switch email on.

TestClient runs background tasks before returning, so what a route queued is
already in `mailer.outbox` when the request comes back.
"""

import pytest

from api.config import Settings, get_settings
from api.mail import get_mailer
from tests.conftest import REQUIRED_ENV

BASE_URL = "https://meshbee.example.org"


class FakeMailer:
    def __init__(self):
        self.outbox = []

    def send(self, to, subject, text, html=None):
        self.outbox.append({"to": to, "subject": subject, "text": text})


def email_settings(**overrides):
    values = {
        "SMTP_HOST": "mailpit",
        "MAIL_FROM": "noreply@meshbee.local",
        "PUBLIC_BASE_URL": BASE_URL,
        **overrides,
    }
    return Settings(_env_file=None, **REQUIRED_ENV, **values)


@pytest.fixture
def mailer(client):
    """Email on, through a fake: the client now sends to `mailer.outbox`."""
    from api import main

    fake = FakeMailer()
    main.app.dependency_overrides[get_settings] = lambda: email_settings()
    main.app.dependency_overrides[get_mailer] = lambda: fake
    return fake


@pytest.fixture
def set_email_settings(client):
    """Email settings overridden with these values, e.g. to switch it off."""
    from api import main

    def _set(**overrides):
        main.app.dependency_overrides[get_settings] = lambda: email_settings(
            **overrides
        )

    return _set
