"""The migration chain and `meshbee_core.models` describe the same schema.

The models are the source; migrations are how a live database follows them.
Alembic's autogenerate diffs columns, types, indexes and foreign keys, but not
CHECK constraints — and the ranges in `limits.py` live in CHECKs. So a change to
a constant that nobody wrote a revision for would pass autogenerate silently.

This builds the schema twice in throwaway Postgres schemas beside `public` —
once with `metadata.create_all()`, once with `upgrade head` — and compares the
catalogs Postgres itself reports. Any difference, a CHECK body included, fails
here with both versions printed.
"""
import psycopg2
import pytest
from sqlalchemy import create_engine

from meshbee_core.migrations import upgrade
from meshbee_core.models import metadata
from tests.conftest import TEST_DB_PARAMS, TEST_DB_URL

FROM_MODELS = "drift_models"
FROM_MIGRATIONS = "drift_migrations"


@pytest.fixture
def scratch_schemas():
    """Two empty schemas, dropped again whatever the test does."""
    connection = psycopg2.connect(**TEST_DB_PARAMS)
    connection.autocommit = True
    cursor = connection.cursor()
    for schema in (FROM_MODELS, FROM_MIGRATIONS):
        cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}")
    try:
        yield cursor
    finally:
        for schema in (FROM_MODELS, FROM_MIGRATIONS):
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        connection.close()


def build_from_models(schema):
    engine = create_engine(TEST_DB_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        metadata.create_all(engine)
    finally:
        engine.dispose()


def catalog(cursor, schema):
    """
    Everything about the schema's tables that a migration could get wrong.

    Only base tables: the baseline still carries the trigger and the view, which
    the models do not describe. Postgres qualifies names from a schema that is
    not on the search_path, so the prefix is stripped to compare like for like.
    """
    def unqualified(rows):
        return sorted(
            tuple(str(v).replace(f"{schema}.", "") if v is not None else None for v in row)
            for row in rows
        )

    cursor.execute(
        """
        SELECT c.table_name, c.column_name, c.data_type, c.character_maximum_length,
               c.numeric_precision, c.numeric_scale, c.is_nullable, c.column_default
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = %s AND t.table_type = 'BASE TABLE'
          AND c.table_name <> 'alembic_version'
        """,
        (schema,),
    )
    columns = unqualified(cursor.fetchall())

    cursor.execute(
        """
        SELECT cl.relname, co.conname, co.contype, pg_get_constraintdef(co.oid)
        FROM pg_constraint co
        JOIN pg_class cl ON cl.oid = co.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = %s AND cl.relname <> 'alembic_version'
        """,
        (schema,),
    )
    constraints = unqualified(cursor.fetchall())

    cursor.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s AND tablename <> 'alembic_version'
        """,
        (schema,),
    )
    indexes = unqualified(cursor.fetchall())

    cursor.execute(
        """
        SELECT cl.relname, obj_description(cl.oid, 'pg_class')
        FROM pg_class cl
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = %s AND cl.relkind = 'r' AND cl.relname <> 'alembic_version'
        """,
        (schema,),
    )
    comments = unqualified(cursor.fetchall())

    return {"columns": columns, "constraints": constraints, "indexes": indexes, "comments": comments}


def test_migrations_build_the_schema_the_models_describe(scratch_schemas):
    build_from_models(FROM_MODELS)
    upgrade(TEST_DB_URL, search_path=FROM_MIGRATIONS)

    models, migrations = catalog(scratch_schemas, FROM_MODELS), catalog(scratch_schemas, FROM_MIGRATIONS)

    for part in models:
        only_models = sorted(set(models[part]) - set(migrations[part]))
        only_migrations = sorted(set(migrations[part]) - set(models[part]))
        assert not (only_models or only_migrations), (
            f"{part} differ — write a revision (alembic revision --autogenerate, "
            f"plus any CHECK change by hand).\n"
            f"  only in the models:     {only_models}\n"
            f"  only in the migrations: {only_migrations}"
        )


def test_upgrade_refuses_an_unstamped_database(scratch_schemas):
    """A pre-Alembic schema gets a clear instruction, not a half-run baseline."""
    from meshbee_core.migrations import UnstampedDatabase

    build_from_models(FROM_MIGRATIONS)

    with pytest.raises(UnstampedDatabase, match="alembic stamp"):
        upgrade(TEST_DB_URL, search_path=FROM_MIGRATIONS)
