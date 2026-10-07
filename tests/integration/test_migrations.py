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
import datetime

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
    Everything about the schema that a migration could get wrong.

    Tables, and the logic a database could hold besides them — views, triggers,
    functions — which the models never describe, so any found after a migration
    is a difference. Postgres qualifies names from a schema that is not on the
    search_path, so the prefix is stripped to compare like for like.
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

    return {
        "columns": columns, "constraints": constraints, "indexes": indexes,
        "comments": comments, "logic": logic(cursor, schema),
    }


def logic(cursor, schema):
    """
    Views, triggers and functions in the schema — what the database would be
    deciding on its own. Functions an extension installed (uuid-ossp's) are not
    ours and are left out.
    """
    cursor.execute(
        """
        SELECT 'view', viewname FROM pg_views WHERE schemaname = %(schema)s
        UNION ALL
        SELECT 'trigger', t.tgname
        FROM pg_trigger t
        JOIN pg_class cl ON cl.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = %(schema)s AND NOT t.tgisinternal
        UNION ALL
        SELECT 'function', p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %(schema)s
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
          )
        """,
        {"schema": schema},
    )
    return sorted(cursor.fetchall())


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


def test_the_migrated_database_holds_no_logic(scratch_schemas):
    """
    No view, trigger or function: the decisions live in meshbee_core.

    The drift test above would already catch one, as a difference from the
    models; this states the rule on its own so the failure says what it means.
    """
    upgrade(TEST_DB_URL, search_path=FROM_MIGRATIONS)

    assert logic(scratch_schemas, FROM_MIGRATIONS) == []


def test_upgrade_refuses_an_unstamped_database(scratch_schemas):
    """A pre-Alembic schema gets a clear instruction, not a half-run baseline."""
    from meshbee_core.migrations import UnstampedDatabase

    build_from_models(FROM_MIGRATIONS)

    with pytest.raises(UnstampedDatabase, match="alembic stamp"):
        upgrade(TEST_DB_URL, search_path=FROM_MIGRATIONS)


# ============================================
# 0002: required columns become NOT NULL
# ============================================


@pytest.fixture
def at_0001(scratch_schemas):
    """A scratch schema at the baseline, and a cursor whose search_path is it."""
    upgrade(TEST_DB_URL, "0001", search_path=FROM_MIGRATIONS)
    scratch_schemas.execute(f"SET search_path TO {FROM_MIGRATIONS}")
    return scratch_schemas


def insert_rows_with_nulls(cursor):
    """One row per table with every column 0002 tightens left NULL."""
    cursor.execute(
        "INSERT INTO utenti (email, password_hash, nome, cognome, ruolo, attivo, data_creazione,"
        " data_attivazione) VALUES ('a@b.org', 'x', 'n', 'c', NULL, NULL, NULL, '2024-01-02')"
    )
    cursor.execute(
        "INSERT INTO nodi (id_nodo, attivo, data_registrazione) VALUES ('N1', NULL, NULL)"
    )
    cursor.execute(
        "INSERT INTO arnie (id_nodo, id_sensore_fisico, attiva, data_installazione)"
        " VALUES ('N1', 'S1', NULL, NULL)"
    )
    cursor.execute(
        "INSERT INTO letture (id_arnia, id_nodo, timestamp) VALUES (1, 'N1', '2024-03-04')"
    )
    cursor.execute(
        "INSERT INTO log_attivita (id_arnia, tipo_attivita, timestamp) VALUES (1, 'altro', NULL)"
    )
    cursor.execute(
        "INSERT INTO utenti_arnie (id_utente, id_arnia, permessi, attivo, data_associazione)"
        " VALUES (1, 1, NULL, true, NULL)"
    )


def row(cursor, query):
    cursor.execute(query)
    return cursor.fetchone()


def test_0002_fills_nulls_without_reviving_anything(at_0001):
    insert_rows_with_nulls(at_0001)

    upgrade(TEST_DB_URL, "0002", search_path=FROM_MIGRATIONS)

    # A NULL flag read as "not true" before, so it must stay off.
    assert row(at_0001, "SELECT ruolo, attivo, data_creazione::date FROM utenti") == (
        "user", False, datetime.date(2024, 1, 2)
    )
    assert row(at_0001, "SELECT attivo, data_registrazione::date FROM nodi") == (
        False, datetime.date(2024, 3, 4)
    )
    assert row(at_0001, "SELECT attiva, data_installazione::date FROM arnie") == (
        False, datetime.date(2024, 3, 4)
    )
    assert row(at_0001, "SELECT timestamp IS NOT NULL FROM log_attivita") == (True,)
    # A NULL permission granted nothing; it still grants nothing.
    assert row(
        at_0001,
        "SELECT permessi, attivo, data_associazione IS NOT NULL,"
        " data_disassociazione IS NOT NULL FROM utenti_arnie",
    ) == ("read", False, True, True)


def test_0002_refuses_rows_it_cannot_fill_and_changes_nothing(at_0001):
    at_0001.execute("INSERT INTO nodi (id_nodo) VALUES ('N1')")
    at_0001.execute("INSERT INTO arnie (id_nodo, id_sensore_fisico) VALUES (NULL, 'S1')")
    at_0001.execute("INSERT INTO utenti (email, password_hash, nome, cognome, ruolo)"
                    " VALUES ('a@b.org', 'x', 'n', 'c', NULL)")

    with pytest.raises(RuntimeError, match="1 arnie without id_nodo"):
        upgrade(TEST_DB_URL, "0002", search_path=FROM_MIGRATIONS)

    assert row(at_0001, "SELECT version_num FROM alembic_version") == ("0001",)
    assert row(at_0001, "SELECT ruolo FROM utenti") == (None,)
