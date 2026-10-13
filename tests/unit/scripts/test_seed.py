"""Unit tests for the seed's orchestration (scripts/seed.py).

Each step against a real database is tests/integration/scripts/test_seed.py.
These pin how `seed()` strings them together: what stops the run, what only
gets reported, and that the pool is released either way.
"""

from contextlib import contextmanager

import pytest

from scripts import seed as seed_script

PASSWORD = "correct-horse-battery-staple"

# Taken before any fixture replaces it.
REAL_CREATE_USERS = seed_script.create_users


@pytest.fixture
def seed_env(monkeypatch, required_env):
    """Valid seed configuration, and every step replaced by a recorder."""
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("USER_PASSWORD", PASSWORD)
    events = []
    ids = {seed_script.ADMIN_EMAIL: 1, seed_script.TEST_EMAIL: 2}

    def record(name, result=None):
        def step(*args, **kwargs):
            events.append((name, *args))
            return result

        return step

    monkeypatch.setattr(seed_script, "init_db_pool", record("init_db_pool"))
    monkeypatch.setattr(seed_script, "close_db_pool", record("close_db_pool"))
    monkeypatch.setattr(seed_script, "create_users", lambda users: ids)
    monkeypatch.setattr(seed_script, "add_sample_apiary", record("apiary", [10, 11]))
    monkeypatch.setattr(seed_script, "add_sample_activity", record("activity"))
    return events


def names(events):
    return [event[0] for event in events]


def test_a_full_run_seeds_the_demo_account_and_releases_the_pool(seed_env):
    """The sample hives go to the test account, the activity to its first hive."""
    seed_script.seed()

    assert names(seed_env) == ["init_db_pool", "apiary", "activity", "close_db_pool"]
    assert seed_env[1] == ("apiary", 2)
    assert seed_env[2] == ("activity", 2, 10)


def test_no_sample_activity_when_the_sample_apiary_was_skipped(seed_env, monkeypatch):
    """An install with its own hives gets no example entry on any of them."""
    monkeypatch.setattr(seed_script, "add_sample_apiary", lambda id_utente: [])

    seed_script.seed()

    assert "activity" not in names(seed_env)


def test_a_sample_data_failure_does_not_fail_the_seed(seed_env, monkeypatch, caplog):
    """
    The demo data is a convenience; the accounts are what the stack needs.

    The failure is logged and the run still completes, so `api` (which waits
    for this container) starts with working logins.
    """

    def broken(id_utente):
        raise RuntimeError("nodo già presente")

    monkeypatch.setattr(seed_script, "add_sample_apiary", broken)

    seed_script.seed()

    assert "Errore dati di esempio" in caplog.text
    assert names(seed_env)[-1] == "close_db_pool"


def test_an_invalid_configuration_stops_before_the_database(seed_env, monkeypatch):
    """A short password exits 1 without opening a single connection."""
    monkeypatch.setenv("ADMIN_PASSWORD", "short")

    with pytest.raises(SystemExit) as exc_info:
        seed_script.seed()

    assert exc_info.value.code == 1
    assert seed_env == []


def test_a_failed_account_stops_the_seed_and_still_releases_the_pool(
    seed_env, monkeypatch, caplog
):
    """
    Exit 1 when an account cannot be created: nothing downstream should start.

    This is the real create_users, on a session that fails to open.
    """

    @contextmanager
    def unreachable():
        raise RuntimeError("database non raggiungibile")
        yield  # pragma: no cover

    monkeypatch.setattr(seed_script, "create_users", REAL_CREATE_USERS)
    monkeypatch.setattr(seed_script, "get_session", unreachable)

    with pytest.raises(SystemExit) as exc_info:
        seed_script.seed()

    assert exc_info.value.code == 1
    assert f"Errore per {seed_script.ADMIN_EMAIL}" in caplog.text
    assert names(seed_env) == ["init_db_pool", "close_db_pool"]
