"""
Schema migrations, managed by Alembic against `meshbee_core.models`.

Two ways in:

- `upgrade(url)` from code — what `scripts/migrate.py` (the compose `migrate`
  service) and the test suite call. It builds the Alembic config in Python, so
  no `alembic.ini` is needed at runtime.
- The `alembic` CLI, for authoring: the repository-root `alembic.ini` points
  here, so `alembic revision --autogenerate -m "..."` works from the repo root
  (in the `api` container).

Either way the database URL is handed to `env.py` as a config *attribute*, not
as `sqlalchemy.url`: the ini parser interpolates `%`, and a URL-encoded
password is full of them.
"""
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

MIGRATIONS_DIR = Path(__file__).parent

# The revision that reproduces the last hand-written schema (migrate_v5.sql).
BASELINE_REVISION = "0001"


class UnstampedDatabase(RuntimeError):
    """The schema exists but Alembic has never been told which revision it is at."""


def alembic_config(url: str, *, search_path: Optional[str] = None) -> Config:
    """
    An Alembic config pointed at this package and at `url`.

    `search_path`, when given, is the Postgres schema the migrations run in —
    the drift test uses it to build a throwaway copy beside `public`.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["url"] = url
    config.attributes["search_path"] = search_path
    return config


def check_stamped(url: str, *, search_path: Optional[str] = None) -> None:
    """
    Refuse to migrate a pre-Alembic database that was never stamped.

    Running the baseline on it would fail half-way on `CREATE TABLE utenti`, and
    stamping it automatically would be a guess about which hand-written
    migrations it has seen. Saying so is cheaper than either.
    """
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names(schema=search_path))
    finally:
        engine.dispose()

    if "utenti" in tables and "alembic_version" not in tables:
        raise UnstampedDatabase(
            "The database already has the Meshbee tables but no alembic_version. "
            "If it is at the migrate_v5.sql schema, mark it once with:\n"
            f"    docker-compose run --rm migrate alembic stamp {BASELINE_REVISION}\n"
            "then start the stack again. See database/README.md."
        )


def upgrade(url: str, revision: str = "head", *, search_path: Optional[str] = None) -> None:
    """Bring the database at `url` up to `revision`."""
    check_stamped(url, search_path=search_path)
    command.upgrade(alembic_config(url, search_path=search_path), revision)
