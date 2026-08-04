"""Shared fixtures for the API test-suite."""
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from api.config import Settings, get_settings

# Connection to the throwaway database defined as `postgres-test` in
# docker-compose.yml. Defaults match that service, so nothing needs configuring
# locally; CI can point them elsewhere.
TEST_DB_PARAMS = {
    "host": os.getenv("TEST_DB_HOST", "postgres-test"),
    "port": int(os.getenv("TEST_DB_PORT", "5432")),
    "dbname": os.getenv("TEST_DB_NAME", "beehive_test"),
    "user": os.getenv("TEST_DB_USER", "beehive_user"),
    "password": os.getenv("TEST_DB_PASSWORD", "test"),
}
SCHEMA_FILE = Path(os.getenv("TEST_DB_SCHEMA", "/database/init.sql"))


@pytest.fixture
def anyio_backend():
    """
    Run `@pytest.mark.anyio` tests on asyncio.

    The anyio pytest plugin ships with fastapi, so async dependencies can be
    awaited directly without pulling in pytest-asyncio.
    """
    return "asyncio"

# The only settings without a default: every Settings instance needs them.
REQUIRED_ENV = {
    "DB_PASSWORD": "test-db-password",
    "JWT_SECRET_KEY": "test-jwt-secret",
}


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """
    Give every test a pristine environment and an empty settings cache.

    The api container is started by docker-compose with DB_HOST=postgres,
    DB_PASSWORD, JWT_SECRET_KEY... already exported, so without this the tests
    would assert against the compose values instead of the declared defaults.
    `get_settings` is lru_cached, so the cache is dropped on both sides of the
    test to keep results independent of execution order.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def required_env(monkeypatch):
    """Export only the settings that have no default."""
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    return dict(REQUIRED_ENV)


@pytest.fixture
def build_settings():
    """
    Build a Settings instance from explicit keyword arguments.

    `_env_file=None` disables the dotenv source: the result must not depend on
    whether a `.env` file happens to sit in the current working directory.
    """
    def _build(**overrides):
        return Settings(_env_file=None, **{**REQUIRED_ENV, **overrides})

    return _build


class FakeCursor:
    """
    Stand-in for the RealDictCursor yielded by `database.get_db_cursor`.

    Only the surface the application actually uses is implemented: `execute`,
    `fetchone` and `fetchall`. Rows are handed out by successive `fetchone`
    calls, in order, so a function running two queries gets `rows[0]` then
    `rows[1]`; once exhausted `fetchone` returns None ("no row found").
    """

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        # Every executed statement, whitespace-collapsed: (sql, params).
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


@pytest.fixture
def fake_db(monkeypatch):
    """
    Replace `get_db_cursor` in the module under test with an in-memory fake.

    Patching targets the *importing* module (`auth`, `main`), not `database`,
    because both do `from database import get_db_cursor` and hold their own
    reference. Pass `error=` to simulate the database being unreachable.

        cursor = fake_db(auth, rows=[{"ruolo": "admin"}])
        assert cursor.queries[0][1] == (42,)
    """
    def _install(module, rows=None, error=None):
        cursor = FakeCursor(rows)

        @contextmanager
        def _fake_get_db_cursor():
            if error is not None:
                raise error
            yield cursor

        monkeypatch.setattr(module, "get_db_cursor", _fake_get_db_cursor)
        return cursor

    return _install


# ============================================
# Real-database fixtures (integration tests)
# ============================================


@pytest.fixture(scope="session")
def test_schema():
    """
    Rebuild the test database from `database/init.sql`, once per pytest run.

    Dropping and reloading the schema here rather than relying on the container
    being fresh means the flush happens on every run, identically on a
    long-running local stack and on a throwaway CI container.

    Loading the *whole* file also keeps init.sql honest: if a migration adds
    something that never made it back into init.sql, or the file stops being
    valid SQL, the suite fails here instead of silently testing a stale schema.
    The example rows it inserts are then truncated, so every test starts from an
    empty, predictable slate.
    """
    try:
        connection = psycopg2.connect(**TEST_DB_PARAMS)
    except psycopg2.OperationalError as exc:
        raise RuntimeError(
            f"Test database unreachable at {TEST_DB_PARAMS['host']}:{TEST_DB_PARAMS['port']} "
            f"({exc.__class__.__name__}). Start it with:\n"
            "    docker-compose --profile test up -d postgres-test\n"
            'Or run the DB-less tests only:  pytest -m "not integration"'
        ) from exc

    connection.autocommit = True
    with connection, connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cursor.execute(SCHEMA_FILE.read_text())
        cursor.execute(
            """
            SELECT string_agg(format('%I', tablename), ', ')
            FROM pg_tables WHERE schemaname = 'public'
            """
        )
        tables = cursor.fetchone()[0]
        cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    connection.close()


@pytest.fixture
def db(test_schema):
    """
    A cursor on a transaction that is rolled back when the test ends.

    Isolation without re-seeding: every test sees the empty schema, writes what
    it needs, and leaves nothing behind. Note this is one long transaction, so
    unlike production (where each `get_db_cursor()` commits) a test does see its
    own earlier writes across several calls.
    """
    connection = psycopg2.connect(**TEST_DB_PARAMS)
    connection.autocommit = False
    cursor = connection.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
    finally:
        connection.rollback()
        cursor.close()
        connection.close()


@pytest.fixture
def use_db(monkeypatch, db):
    """
    Point the module under test at the rolled-back test transaction.

    Same seam as `fake_db`, real SQL underneath: `use_db(auth)` makes
    `auth.authenticate_user` run its queries against postgres-test.
    """
    def _install(module):
        @contextmanager
        def _test_get_db_cursor():
            yield db

        monkeypatch.setattr(module, "get_db_cursor", _test_get_db_cursor)
        return db

    return _install
