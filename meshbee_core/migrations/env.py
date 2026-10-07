"""
Alembic environment: compare against `meshbee_core.models`, connect to the URL
the caller supplied, or to the one `CoreSettings` builds from the environment.
"""
from alembic import context
from sqlalchemy import create_engine, pool

from meshbee_core import models
from meshbee_core.config import get_core_settings

config = context.config
target_metadata = models.metadata


def database_url() -> str:
    # Set by meshbee_core.migrations.alembic_config; absent when the CLI runs
    # from alembic.ini, which deliberately holds no URL.
    return config.attributes.get("url") or get_core_settings().database_url


def run_migrations_offline() -> None:
    """`alembic upgrade --sql`: print the SQL instead of running it."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    search_path = config.attributes.get("search_path")
    connect_args = {"options": f"-csearch_path={search_path}"} if search_path else {}
    engine = create_engine(database_url(), poolclass=pool.NullPool, connect_args=connect_args)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
