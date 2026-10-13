"""Tests for the one-shot migration step (scripts/migrate.py).

`api`, `mqtt-handler` and `seed` all wait for the `migrate` service to exit 0,
so its exit status is the contract: 0 only when the schema is at head.
"""

import logging
import runpy
import sys

import pytest

from meshbee_core import migrations
from meshbee_core.migrations import UnstampedDatabase
from scripts import migrate


def test_the_schema_is_upgraded_on_the_configured_database(
    monkeypatch, required_env, caplog
):
    """The URL comes from the same DB_* settings every other service reads."""
    upgraded = []
    monkeypatch.setenv("DB_HOST", "postgres")
    monkeypatch.setattr(migrate, "upgrade", upgraded.append)

    with caplog.at_level(logging.INFO):
        migrate.main()

    [url] = upgraded
    assert "@postgres:5432/" in url
    assert "Schema aggiornato" in caplog.text


def test_an_unstamped_database_stops_the_stack_with_the_fix(
    monkeypatch, required_env, caplog
):
    """
    Exit 1, so nothing starts on a schema Alembic does not know.

    The message carries the `alembic stamp` command: it is all an operator
    upgrading a pre-Alembic install sees.
    """

    def unstamped(url):
        raise UnstampedDatabase("... alembic stamp 0001 ...")

    monkeypatch.setattr(migrate, "upgrade", unstamped)

    with pytest.raises(SystemExit) as exc_info:
        migrate.main()

    assert exc_info.value.code == 1
    assert "alembic stamp 0001" in caplog.text


def test_any_other_failure_is_not_reported_as_success(monkeypatch, required_env):
    """A failed migration must never log "Schema aggiornato" and exit 0."""

    def broken(url):
        raise RuntimeError("revision non applicabile")

    monkeypatch.setattr(migrate, "upgrade", broken)

    with pytest.raises(RuntimeError):
        migrate.main()


def test_running_the_script_migrates(monkeypatch, required_env):
    """The compose service runs `python -m scripts.migrate`; that must reach main()."""
    upgraded = []
    monkeypatch.setattr(migrations, "upgrade", upgraded.append)

    # Run it fresh, as `python -m` does, rather than over the imported copy.
    monkeypatch.delitem(sys.modules, "scripts.migrate")

    runpy.run_module("scripts.migrate", run_name="__main__")

    assert len(upgraded) == 1
