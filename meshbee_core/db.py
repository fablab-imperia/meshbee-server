"""
Database engine and sessions.

Shared by both entry points. `init_db_pool` takes its settings as an argument
rather than importing a singleton, so the library never decides where its
configuration comes from — the process that owns the pool does.

The contract the rest of the library relies on is unchanged from the psycopg2
days: **the caller owns the session**. Services and repositories take one and
never open one, and one `with get_session()` block is one transaction —
committed on a clean exit, rolled back on an exception.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from meshbee_core.config import CoreSettings

logger = logging.getLogger(__name__)

# SQLSTATE codes: standard SQL, not driver constants, so nothing here imports
# psycopg2.
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"

engine: Engine | None = None


def init_db_pool(settings: CoreSettings, *, maxconn: int = 20) -> None:
    """Create the engine and its connection pool."""
    global engine
    try:
        # QueuePool is thread-safe, which lets FastAPI run the synchronous
        # routes in its threadpool. pre_ping replaces a connection the server
        # dropped (a Postgres restart) instead of failing the next request.
        # hide_parameters keeps bound values out of exception text: every
        # caller logs `{e}`, and an INSERT INTO utenti carries a password hash.
        engine = create_engine(
            settings.database_url,
            pool_size=maxconn,
            max_overflow=0,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        logger.info("Pool di connessioni database inizializzato")
    except Exception as e:
        logger.error(f"Errore inizializzazione database pool: {e}")
        raise


def close_db_pool() -> None:
    """Close every pooled connection."""
    global engine
    if engine:
        engine.dispose()
        engine = None
        logger.info("Pool di connessioni database chiuso")


@contextmanager
def get_session() -> Iterator[Session]:
    """
    One transaction: commit on a clean exit, roll back on an exception.

    `expire_on_commit=False` because repositories hand back plain dicts, and
    nothing should reach for the database again once the block has ended.
    """
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Errore database: {e}")
        raise
    finally:
        session.close()


@contextmanager
def integrity_errors(*, unique: Exception = None, foreign_key: Exception = None):
    """
    Turn a constraint violation into the domain error the caller names.

    A service knows what a duplicate email or a missing arnia *means*; the
    database only knows which constraint failed. Anything not mapped — a CHECK
    violation, say — propagates unchanged.
    """
    try:
        yield
    except IntegrityError as exc:
        mapped = {
            UNIQUE_VIOLATION: unique,
            FOREIGN_KEY_VIOLATION: foreign_key,
        }.get(getattr(exc.orig, "pgcode", None))
        if mapped is None:
            raise
        raise mapped from exc


def ping(session: Session) -> None:
    """Cheapest possible round-trip, for health checks."""
    session.exec(select(func.now())).one()
