"""Tests for the test-email script (scripts/send_test_mail.py).

The mailer is replaced by a recorder: the script's job is to read the settings,
hand them to the mailer, and turn the outcome into an exit code.
"""

import pytest

from meshbee_core.errors import Unavailable
from scripts import send_test_mail as script

SMTP_ENV = {
    "SMTP_HOST": "mailpit",
    "SMTP_PORT": "1025",
    "SMTP_SECURITY": "none",
    "MAIL_FROM": "Meshbee <noreply@meshbee.local>",
}


@pytest.fixture
def smtp_env(monkeypatch, required_env):
    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def sent(monkeypatch):
    """Every (config, args) the script asked a mailer to send."""
    calls = []

    class RecordingMailer:
        def __init__(self, config):
            self.config = config

        def send(self, *args):
            calls.append((self.config, args))

    monkeypatch.setattr(script, "Mailer", RecordingMailer)
    return calls


def test_it_sends_one_message_with_the_configured_server(smtp_env, sent):
    assert script.main(["bee@example.org"]) == 0

    [(config, (to, subject, _text))] = sent
    assert (config.host, config.port, config.security) == ("mailpit", 1025, "none")
    assert (to, subject) == ("bee@example.org", script.SUBJECT)


def test_with_email_disabled_it_fails_and_sends_nothing(required_env, sent, caplog):
    assert script.main(["bee@example.org"]) == 1

    assert sent == []
    assert "SMTP_HOST" in caplog.text


def test_a_failed_send_is_exit_code_1(smtp_env, monkeypatch, caplog):
    class BrokenMailer:
        def __init__(self, config):
            pass

        def send(self, *args):
            raise Unavailable("Servizio email non disponibile")

    monkeypatch.setattr(script, "Mailer", BrokenMailer)

    assert script.main(["bee@example.org"]) == 1
    assert "Servizio email non disponibile" in caplog.text


def test_a_recipient_is_required(smtp_env):
    with pytest.raises(SystemExit):
        script.main([])
