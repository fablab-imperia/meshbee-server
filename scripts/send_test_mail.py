#!/usr/bin/env python3
"""Send one test email with the API's SMTP settings.

Checks a provider end to end (host, port, TLS mode, credentials, sender domain)
without going through any flow that needs email:

    docker-compose exec api python -m scripts.send_test_mail you@example.org

Exits 0 when the server accepted the message, 1 when email is disabled or the
send failed. The server's reply is in the log line above the error.
"""

import argparse
import logging
import sys

from api.config import get_settings
from meshbee_core.errors import Unavailable
from meshbee_core.mail import Mailer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SUBJECT = "Meshbee: test email"
TEXT = (
    "This is a test message from the Meshbee server.\n\n"
    "If you can read it, outgoing email is configured correctly.\n"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("to", help="recipient address")
    args = parser.parse_args(argv)

    smtp = get_settings().smtp_config
    if smtp is None:
        logger.error("Email is disabled: set SMTP_HOST and MAIL_FROM (see README.md)")
        return 1

    logger.info(
        f"Sending to {args.to} via {smtp.host}:{smtp.port} "
        f"(security={smtp.security}, login={'yes' if smtp.username else 'no'})"
    )
    try:
        Mailer(smtp).send(args.to, SUBJECT, TEXT)
    except Unavailable as e:
        logger.error(str(e))
        return 1
    logger.info("Accepted by the server. Check the inbox (and the spam folder).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
