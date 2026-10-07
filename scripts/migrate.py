#!/usr/bin/env python3
"""
Bring the database schema up to date, then exit.

Run by the one-shot `migrate` compose service before anything else touches the
database: `api`, `mqtt-handler` and `seed` all wait for it to exit 0. Running it
again is a no-op when the schema is already at head.
"""

import logging
import sys

from meshbee_core.config import CoreSettings
from meshbee_core.migrations import UnstampedDatabase, upgrade

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        upgrade(CoreSettings().database_url)
    except UnstampedDatabase as e:
        logger.error(str(e))
        sys.exit(1)
    logger.info("Schema aggiornato")


if __name__ == "__main__":
    main()
