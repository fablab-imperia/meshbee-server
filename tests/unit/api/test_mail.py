"""Tests for email in the API (api/mail.py), and how its failure maps to HTTP.

The mailer is a fake throughout: nothing here opens a connection. What is pinned
is that sending happens after the response, that a failure there is logged and
never surfaces, and that a route which does wait on the mailer answers 503.
"""

import logging
from contextlib import nullcontext

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import main
from api.mail import get_mailer, send_later
from meshbee_core.errors import Unavailable
from meshbee_core.mail import Mailer

RESET_LINK = "https://meshbee.example.org/reset-password#token=abc"


class FakeMailer:
    """Records each message, or raises `Unavailable` like a broken server."""

    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send(self, to, subject, text, html=None):
        if self.fail:
            raise Unavailable("Servizio email non disponibile")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


def client_for(mailer) -> TestClient:
    """An app with one route that queues a message through `send_later`."""
    app = FastAPI()

    @app.post("/notify")
    def notify(background_tasks: BackgroundTasks, mailer=Depends(get_mailer)):
        if mailer is None:
            return {"queued": False}
        send_later(background_tasks, mailer, "bee@example.org", "Reset", RESET_LINK)
        return {"queued": True}

    app.dependency_overrides[get_mailer] = lambda: mailer
    return TestClient(app)


def test_a_queued_message_is_sent_after_the_response():
    mailer = FakeMailer()

    response = client_for(mailer).post("/notify")

    assert response.json() == {"queued": True}
    assert mailer.sent == [
        {"to": "bee@example.org", "subject": "Reset", "text": RESET_LINK, "html": None}
    ]


def test_a_failed_send_does_not_reach_the_client_and_is_logged(caplog):
    """The response has gone out already: the failure is a log line, not a 500."""
    with caplog.at_level(logging.WARNING, logger="api.mail"):
        response = client_for(FakeMailer(fail=True)).post("/notify")

    assert response.status_code == 200
    assert "bee@example.org" in caplog.text
    assert "Reset" in caplog.text
    assert RESET_LINK not in caplog.text


def test_without_a_mailer_the_route_knows_email_is_off():
    assert client_for(None).post("/notify").json() == {"queued": False}


def test_get_mailer_is_none_when_email_is_disabled(build_settings):
    assert get_mailer(build_settings()) is None


def test_get_mailer_builds_one_from_the_settings(build_settings):
    settings = build_settings(
        SMTP_HOST="mailpit", SMTP_SECURITY="none", MAIL_FROM="noreply@meshbee.local"
    )

    mailer = get_mailer(settings)

    assert isinstance(mailer, Mailer)
    assert (mailer.config.host, mailer.config.port) == ("mailpit", 25)


def test_unavailable_is_a_503(monkeypatch):
    """A route that waits on the mailer tells the client to retry later, not 500."""
    monkeypatch.setattr(main, "get_session", nullcontext)

    with pytest.raises(HTTPException) as exc_info:
        with main.db_operation("invio email"):
            raise Unavailable("Servizio email non disponibile")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Servizio email non disponibile"
