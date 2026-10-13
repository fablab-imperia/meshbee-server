"""Tests for the SMTP mailer (meshbee_core/mail.py).

`smtplib` is replaced by a recorder, so nothing here touches the network: what
is pinned is how each setting turns into calls on the SMTP connection, and that
a failure reaches the caller as `Unavailable` without leaking the setup.
"""

import logging
import smtplib

import pytest

from meshbee_core import mail
from meshbee_core.errors import Unavailable
from meshbee_core.mail import Mailer, SmtpConfig, default_port

PASSWORD = "s3cr3t-smtp"
RESET_LINK = "https://meshbee.example.org/reset-password#token=abc"


class FakeSMTP:
    """Records what the mailer does to the connection; `fail_on` names a step that raises."""

    instances: list[FakeSMTP] = []
    fail_on: dict[str, BaseException] = {}

    def __init__(self, host, port, timeout=None, context=None):
        self.kind = type(self).__name__
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls = []
        self.sent = []
        self.closed = False
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step):
        if step in FakeSMTP.fail_on:
            raise FakeSMTP.fail_on[step]

    def starttls(self, context=None):
        self.calls.append("starttls")
        self._maybe_fail("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))
        self._maybe_fail("login")

    def send_message(self, message):
        self.calls.append("send_message")
        self._maybe_fail("send_message")
        self.sent.append(message)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeSMTP_SSL(FakeSMTP):  # noqa: N801 — mirrors smtplib's name
    pass


@pytest.fixture(autouse=True)
def fake_smtplib(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_on = {}
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP_SSL)
    return FakeSMTP


def make_config(**overrides) -> SmtpConfig:
    values = {
        "host": "smtp.example.org",
        "port": 587,
        "security": "starttls",
        "sender": "Meshbee <noreply@example.org>",
        "username": "mailer",
        "password": PASSWORD,
        "timeout": 7.5,
    }
    return SmtpConfig(**{**values, **overrides})


def only_connection() -> FakeSMTP:
    assert len(FakeSMTP.instances) == 1
    return FakeSMTP.instances[0]


# ============================================
# Connecting
# ============================================


def test_ssl_connects_with_implicit_tls():
    Mailer(make_config(security="ssl", port=465)).send("a@example.org", "S", "T")

    smtp = only_connection()
    assert smtp.kind == "FakeSMTP_SSL"
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.org", 465, 7.5)
    assert smtp.context is not None
    assert "starttls" not in smtp.calls


def test_starttls_upgrades_before_logging_in():
    Mailer(make_config()).send("a@example.org", "S", "T")

    smtp = only_connection()
    assert smtp.kind == "FakeSMTP"
    assert smtp.timeout == 7.5
    assert smtp.calls == ["starttls", ("login", "mailer", PASSWORD), "send_message"]


def test_none_sends_in_the_clear():
    """For a relay on the same network, e.g. Mailpit in development."""
    Mailer(make_config(security="none", port=1025)).send("a@example.org", "S", "T")

    smtp = only_connection()
    assert smtp.kind == "FakeSMTP"
    assert "starttls" not in smtp.calls


def test_without_a_username_there_is_no_login():
    """A relay that needs no credentials must not be sent an empty login."""
    Mailer(make_config(username=None, password=None)).send("a@example.org", "S", "T")

    assert only_connection().calls == ["starttls", "send_message"]


def test_the_connection_is_closed_after_sending():
    Mailer(make_config()).send("a@example.org", "S", "T")

    assert only_connection().closed


@pytest.mark.parametrize(
    ("security", "port"), [("ssl", 465), ("starttls", 587), ("none", 25)]
)
def test_default_port_follows_the_security_mode(security, port):
    assert default_port(security) == port


# ============================================
# The message
# ============================================


def test_the_message_carries_the_headers_and_the_text():
    Mailer(make_config()).send("bee@example.org", "Hello", "Plain body\n")

    message = only_connection().sent[0]
    assert message["From"] == "Meshbee <noreply@example.org>"
    assert message["To"] == "bee@example.org"
    assert message["Subject"] == "Hello"
    assert message["Date"]
    assert message["Message-ID"].endswith("@example.org>")
    assert not message.is_multipart()
    assert message.get_content() == "Plain body\n"


def test_html_is_added_as_an_alternative_to_the_text():
    Mailer(make_config()).send("a@example.org", "S", "Plain\n", "<p>Rich</p>")

    message = only_connection().sent[0]
    assert message.get_content_type() == "multipart/alternative"
    parts = [part.get_content_type() for part in message.iter_parts()]
    assert parts == ["text/plain", "text/html"]


def test_non_ascii_text_and_subject_are_encoded():
    """Italian text must survive the trip: accents in the subject and the body."""
    Mailer(make_config()).send("a@example.org", "Attività", "Città è più\n")

    message = only_connection().sent[0]
    assert message["Subject"] == "Attività"
    assert message.get_content() == "Città è più\n"


# ============================================
# Failures
# ============================================


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("connect", ConnectionRefusedError("refused")),
        ("connect", TimeoutError("timed out")),
        ("starttls", smtplib.SMTPNotSupportedError("no STARTTLS")),
        ("login", smtplib.SMTPAuthenticationError(535, b"bad credentials")),
        ("send_message", smtplib.SMTPRecipientsRefused({})),
    ],
)
def test_every_failure_becomes_unavailable(fake_smtplib, step, error):
    fake_smtplib.fail_on = {step: error}

    with pytest.raises(Unavailable) as exc_info:
        Mailer(make_config()).send("a@example.org", "S", "T")

    # The driver's exception is not chained: a traceback shows only Unavailable.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


def test_a_failed_starttls_closes_the_connection(fake_smtplib):
    fake_smtplib.fail_on = {"starttls": smtplib.SMTPNotSupportedError("no")}

    with pytest.raises(Unavailable):
        Mailer(make_config()).send("a@example.org", "S", "T")

    assert only_connection().closed


def test_a_failure_tells_the_caller_nothing_about_the_setup(fake_smtplib):
    """The message may reach an API client as a 503: no host, user or password in it."""
    fake_smtplib.fail_on = {"login": smtplib.SMTPAuthenticationError(535, b"nope")}

    with pytest.raises(Unavailable) as exc_info:
        Mailer(make_config()).send("a@example.org", "S", "T")

    text = str(exc_info.value)
    for secret in ("smtp.example.org", "mailer", PASSWORD):
        assert secret not in text


def test_a_failure_is_logged_without_password_or_body(fake_smtplib, caplog):
    """The log says which server failed and why, and never the secret or the link."""
    fake_smtplib.fail_on = {"login": smtplib.SMTPAuthenticationError(535, b"nope")}

    with caplog.at_level(logging.INFO, logger="meshbee_core.mail"):
        with pytest.raises(Unavailable):
            Mailer(make_config()).send("a@example.org", "Reset", RESET_LINK)

    assert "smtp.example.org:587" in caplog.text
    assert "SMTPAuthenticationError" in caplog.text
    assert PASSWORD not in caplog.text
    assert RESET_LINK not in caplog.text


def test_a_success_is_logged_without_the_body(caplog):
    with caplog.at_level(logging.INFO, logger="meshbee_core.mail"):
        Mailer(make_config()).send("a@example.org", "Reset", RESET_LINK)

    assert "a@example.org" in caplog.text
    assert RESET_LINK not in caplog.text


def test_the_password_is_not_in_the_config_repr():
    assert PASSWORD not in repr(make_config())


# ============================================
# One recipient, a verified server
# ============================================


@pytest.mark.parametrize(
    "to",
    [
        "a@example.org, b@example.org",
        "a@example.org;b@example.org",
        "Name <a@example.org>",
        "a@example.org\nBcc: b@example.org",
        "a @example.org",
        "not-an-email",
        "a@b@example.org",
    ],
)
def test_only_a_single_plain_address_is_sent_to(fake_smtplib, to):
    """A list would reach every address on it, past any cap that counts messages."""
    with pytest.raises(Unavailable):
        Mailer(make_config()).send(to, "S", "T")

    assert FakeSMTP.instances == []


def test_the_tls_context_verifies_the_server():
    import ssl

    context = mail.tls_context()

    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_both_tls_modes_use_the_verifying_context(monkeypatch):
    marker = object()
    monkeypatch.setattr(mail, "tls_context", lambda: marker)
    seen = []
    monkeypatch.setattr(
        FakeSMTP, "starttls", lambda self, context=None: seen.append(context)
    )

    Mailer(make_config(security="ssl", port=465)).send("a@example.org", "S", "T")
    Mailer(make_config(security="starttls")).send("a@example.org", "S", "T")

    assert FakeSMTP.instances[0].context is marker
    assert seen == [marker]
