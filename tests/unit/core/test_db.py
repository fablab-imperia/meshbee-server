"""Unit tests for the engine and session helpers (meshbee_core/db.py).

The transaction contract is what the whole library leans on: services never
commit, so a `with get_session()` block is the only place that does. These pin
it with a recording session; tests/integration/core/test_db.py runs the real
engine against postgres-test.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from meshbee_core import db as core_db
from meshbee_core.errors import Conflict, NotFound


class RecordingSession:
    """Stands in for sqlmodel.Session and records what the block did with it."""

    instances = []

    def __init__(self, engine, expire_on_commit=True):
        self.engine = engine
        self.expire_on_commit = expire_on_commit
        self.calls = []
        RecordingSession.instances.append(self)

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def recorded(monkeypatch):
    RecordingSession.instances = []
    monkeypatch.setattr(core_db, "Session", RecordingSession)
    return RecordingSession.instances


def test_a_clean_block_commits_and_closes(recorded):
    """One block, one transaction: what it wrote is kept."""
    with core_db.get_session():
        pass

    [session] = recorded
    assert session.calls == ["commit", "close"]


def test_a_failing_block_rolls_back_closes_and_reraises(recorded):
    """
    Half a write must never be committed, and the caller must still see why.

    The entry points translate the exception (a 404, a dropped MQTT message),
    so swallowing it here would turn a failure into a silent success.
    """
    with pytest.raises(NotFound):
        with core_db.get_session():
            raise NotFound("Arnia non trovata")

    [session] = recorded
    assert session.calls == ["rollback", "close"]


def test_rows_stay_readable_after_the_block(recorded):
    """
    expire_on_commit=False: a returned object must not reach back to the database.

    The session is closed by then, so an expired attribute would raise instead
    of returning the value just written.
    """
    with core_db.get_session():
        pass

    assert recorded[0].expire_on_commit is False


class FakeEngine:
    disposed = False

    def dispose(self):
        self.disposed = True


def test_the_pool_is_capped_and_survives_a_database_restart(
    monkeypatch, build_core_settings
):
    """
    pool_size with no overflow is a hard cap on connections per process.

    pre_ping replaces a connection Postgres dropped instead of failing the next
    request, and hide_parameters keeps bound values (password hashes) out of
    every error message that gets logged.
    """
    created = {}

    def fake_create_engine(url, **kwargs):
        created.update(url=url, **kwargs)
        return FakeEngine()

    monkeypatch.setattr(core_db, "create_engine", fake_create_engine)
    monkeypatch.setattr(core_db, "engine", None)
    settings = build_core_settings()

    core_db.init_db_pool(settings, maxconn=3)

    assert created["url"] == settings.database_url
    assert created["pool_size"] == 3
    assert created["max_overflow"] == 0
    assert created["pool_pre_ping"] is True
    assert created["hide_parameters"] is True
    assert isinstance(core_db.engine, FakeEngine)


def test_a_failed_pool_setup_is_raised_to_the_process(monkeypatch, build_core_settings):
    """The entry points exit on it; a process with no database must not carry on."""

    def broken_create_engine(url, **kwargs):
        raise RuntimeError("driver non disponibile")

    monkeypatch.setattr(core_db, "create_engine", broken_create_engine)

    with pytest.raises(RuntimeError, match="driver non disponibile"):
        core_db.init_db_pool(build_core_settings())


def test_closing_the_pool_disposes_it_once(monkeypatch):
    """Shutdown paths can call it twice (signal, then finally) without failing."""
    engine = FakeEngine()
    monkeypatch.setattr(core_db, "engine", engine)

    core_db.close_db_pool()
    core_db.close_db_pool()

    assert engine.disposed
    assert core_db.engine is None


def violation(sqlstate):
    """An IntegrityError as psycopg 3 raises it: the code is on `.orig.sqlstate`."""

    class Orig(Exception):
        pass

    orig = Orig()
    orig.sqlstate = sqlstate
    return IntegrityError("INSERT ...", {}, orig)


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [(core_db.UNIQUE_VIOLATION, Conflict), (core_db.FOREIGN_KEY_VIOLATION, NotFound)],
)
def test_a_mapped_violation_becomes_the_named_domain_error(sqlstate, expected):
    """The service names what the violation means; the entry point maps that to a status."""
    error = violation(sqlstate)

    with pytest.raises(expected) as exc_info:
        with core_db.integrity_errors(
            unique=Conflict("Email già registrata"),
            foreign_key=NotFound("Arnia non trovata"),
        ):
            raise error

    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize(
    "sqlstate",
    [
        "23514",  # check_violation: never something a caller can explain
        core_db.FOREIGN_KEY_VIOLATION,  # a kind this caller did not map
        None,  # a driver error without a code
    ],
)
def test_an_unmapped_violation_propagates_unchanged(sqlstate):
    """Guessing a meaning for a failure the service did not anticipate would hide a bug."""
    error = violation(sqlstate)

    with pytest.raises(IntegrityError) as exc_info:
        with core_db.integrity_errors(unique=Conflict("Email già registrata")):
            raise error

    assert exc_info.value is error
