"""
Gestione connessione database

Shared by both entry points. `init_db_pool` takes its settings as an argument
rather than importing a singleton, so the library never decides where its
configuration comes from — the process that owns the pool does.
"""
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
import logging

from meshbee_core.config import CoreSettings

logger = logging.getLogger(__name__)

# Pool di connessioni
db_pool: SimpleConnectionPool = None


def init_db_pool(settings: CoreSettings, *, maxconn: int = 20):
    """Inizializza il pool di connessioni al database"""
    global db_pool
    try:
        db_pool = SimpleConnectionPool(
            minconn=1,
            maxconn=maxconn,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD.get_secret_value()
        )
        logger.info("Pool di connessioni database inizializzato")
    except Exception as e:
        logger.error(f"Errore inizializzazione database pool: {e}")
        raise


def close_db_pool():
    """Chiude il pool di connessioni"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        logger.info("Pool di connessioni database chiuso")


@contextmanager
def get_db_connection():
    """
    Context manager per ottenere una connessione dal pool
    
    Yields:
        connessione database con cursor RealDictCursor
    """
    conn = None
    try:
        conn = db_pool.getconn()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Errore database: {e}")
        raise
    finally:
        if conn:
            db_pool.putconn(conn)


@contextmanager
def get_db_cursor():
    """
    Context manager per ottenere un cursor dal pool
    
    Yields:
        cursor RealDictCursor
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
        finally:
            cursor.close()


def ping(cursor) -> None:
    """Cheapest possible round-trip, for health checks."""
    cursor.execute("SELECT 1")
