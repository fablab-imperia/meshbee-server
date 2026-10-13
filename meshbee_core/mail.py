"""Outgoing email over SMTP.

Provider-neutral on purpose: any server that speaks SMTP works (Resend, Brevo,
SES, a fablab's own server, an unauthenticated local relay, Mailpit in
development). Standard library only, no framework, no database.

The caller decides whether email is configured at all and builds the
`SmtpConfig`; this module only sends. A failure of any kind reaches the caller
as `errors.Unavailable`, never as an `smtplib` or socket exception. The log names
the server and the recipient; the password and the message body (which may hold
a reset link) appear nowhere.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Literal

from meshbee_core.errors import Unavailable

logger = logging.getLogger(__name__)

SmtpSecurity = Literal["ssl", "starttls", "none"]

# The usual port for each kind of connection, when none is configured.
DEFAULT_PORTS: dict[str, int] = {"ssl": 465, "starttls": 587, "none": 25}


def default_port(security: SmtpSecurity) -> int:
    """The conventional port for `security`: 465 (SMTPS), 587 (submission) or 25."""
    return DEFAULT_PORTS[security]


@dataclass(frozen=True)
class SmtpConfig:
    """Where and how to connect, and who the mail is from.

    `security`:
    - `ssl`: implicit TLS from the first byte (SMTPS, usually 465);
    - `starttls`: plain connection upgraded to TLS before login (usually 587);
    - `none`: no encryption at all — only for a relay on the same host or network.

    Without a `username` the mailer does not log in, for relays that need none.
    """

    host: str
    port: int
    security: SmtpSecurity
    sender: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    timeout: float = 10.0


class Mailer:
    """Sends one message per call, on a fresh connection."""

    def __init__(self, config: SmtpConfig):
        self.config = config

    def build_message(
        self, to: str, subject: str, text: str, html: str | None = None
    ) -> EmailMessage:
        """A plain-text message, with an HTML alternative when `html` is given."""
        message = EmailMessage()
        message["From"] = self.config.sender
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        domain = parseaddr(self.config.sender)[1].rpartition("@")[2] or None
        message["Message-ID"] = make_msgid(domain=domain)
        message.set_content(text)
        if html is not None:
            message.add_alternative(html, subtype="html")
        return message

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        """Send one message, or raise `Unavailable` saying which server failed."""
        message = self.build_message(to, subject, text, html)
        where = f"{self.config.host}:{self.config.port}"
        try:
            with self._connect() as smtp:
                if self.config.username:
                    smtp.login(self.config.username, self.config.password or "")
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as e:
            # The server's reply goes to the log, for whoever runs the install; the
            # caller (and through it an API client) learns nothing about the setup.
            logger.warning(f"Email to {to} via {where} failed: {type(e).__name__}: {e}")
            raise Unavailable("Servizio email non disponibile") from None
        logger.info(f"Email '{subject}' sent to {to} via {where}")

    def _connect(self) -> smtplib.SMTP:
        config = self.config
        if config.security == "ssl":
            return smtplib.SMTP_SSL(
                config.host,
                config.port,
                timeout=config.timeout,
                context=ssl.create_default_context(),
            )
        smtp = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
        if config.security == "starttls":
            try:
                smtp.starttls(context=ssl.create_default_context())
            except BaseException:
                smtp.close()
                raise
        return smtp
