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

import psycopg
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
    connection = psycopg.connect(**TEST_DB_PARAMS)
    connection.autocommit = True
    cursor = connection.cursor()
    for schema in (FROM_MODELS, FROM_MIGRATIONS):
        cursor.execute(
            f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}"
        )
    try:
        yield cursor
    finally:
        for schema in (FROM_MODELS, FROM_MIGRATIONS):
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        connection.close()


def build_from_models(schema):
    engine = create_engine(
        TEST_DB_URL, connect_args={"options": f"-csearch_path={schema}"}
    )
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
            tuple(
                str(v).replace(f"{schema}.", "") if v is not None else None for v in row
            )
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
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "comments": comments,
        "logic": logic(cursor, schema),
    }


def logic(cursor, schema):
    """
    Views, triggers and functions in the schema — what the database would be
    deciding on its own. Functions an extension installs are not ours and are
    left out; which extensions exist is checked separately.
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

    models, migrations = (
        catalog(scratch_schemas, FROM_MODELS),
        catalog(scratch_schemas, FROM_MIGRATIONS),
    )

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
    # plpgsql ships with every database; anything else was installed by us.
    scratch_schemas.execute(
        "SELECT extname FROM pg_extension WHERE extname <> 'plpgsql'"
    )
    assert scratch_schemas.fetchall() == []


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
        "user",
        False,
        datetime.date(2024, 1, 2),
    )
    assert row(at_0001, "SELECT attivo, data_registrazione::date FROM nodi") == (
        False,
        datetime.date(2024, 3, 4),
    )
    assert row(at_0001, "SELECT attiva, data_installazione::date FROM arnie") == (
        False,
        datetime.date(2024, 3, 4),
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
    at_0001.execute(
        "INSERT INTO arnie (id_nodo, id_sensore_fisico) VALUES (NULL, 'S1')"
    )
    at_0001.execute(
        "INSERT INTO utenti (email, password_hash, nome, cognome, ruolo)"
        " VALUES ('a@b.org', 'x', 'n', 'c', NULL)"
    )

    with pytest.raises(RuntimeError, match="1 arnie without id_nodo"):
        upgrade(TEST_DB_URL, "0002", search_path=FROM_MIGRATIONS)

    assert row(at_0001, "SELECT version_num FROM alembic_version") == ("0001",)
    assert row(at_0001, "SELECT ruolo FROM utenti") == (None,)


# ============================================
# 0005: ownership, apiaries, sharing per apiary
# ============================================


@pytest.fixture
def before_0005(scratch_schemas):
    """
    A schema at 0004 with three users, three nodes and per-hive access:

    - N1 holds S1 (user 1 admin, user 2 read) and S2 (user 2 write, user 3
      admin but revoked): one hive each for users 1 and 2, a tie;
    - N2 holds S3 (user 2 read);
    - N3 holds S4, which nobody has access to.
    """
    upgrade(TEST_DB_URL, "0004", search_path=FROM_MIGRATIONS)
    cursor = scratch_schemas
    cursor.execute(f"SET search_path TO {FROM_MIGRATIONS}")
    cursor.execute(
        "INSERT INTO utenti (email, password_hash, nome, cognome) VALUES"
        " ('a@b.org', 'x', 'A', 'A'), ('c@d.org', 'x', 'C', 'C'), ('e@f.org', 'x', 'E', 'E')"
    )
    cursor.execute("INSERT INTO nodi (id_nodo) VALUES ('N1'), ('N2'), ('N3')")
    cursor.execute(
        "INSERT INTO arnie (id_nodo, id_sensore_fisico) VALUES"
        " ('N1', 'S1'), ('N1', 'S2'), ('N2', 'S3'), ('N3', 'S4')"
    )
    cursor.execute(
        "INSERT INTO utenti_arnie (id_utente, id_arnia, permessi, attivo) VALUES"
        " (1, 1, 'admin', true), (2, 1, 'read', true), (2, 2, 'write', true),"
        " (3, 2, 'admin', false), (2, 3, 'read', true)"
    )
    return cursor


def rows(cursor, query):
    cursor.execute(query)
    return cursor.fetchall()


def test_0005_turns_access_into_ownership_and_shares(before_0005):
    cursor = before_0005

    upgrade(TEST_DB_URL, "0005", search_path=FROM_MIGRATIONS)

    # Every account gets its Default.
    assert rows(
        cursor,
        "SELECT id_utente_proprietario, nome_apiario, predefinito FROM apiari ORDER BY 1",
    ) == [(1, "Default", True), (2, "Default", True), (3, "Default", True)]
    # N1 is a tie between users 1 and 2: the lowest id wins. A revoked
    # association counts for nothing; N3 had no access at all and stays unassigned.
    assert rows(cursor, "SELECT id_nodo, id_proprietario FROM nodi ORDER BY 1") == [
        ("N1", 1),
        ("N2", 2),
        ("N3", None),
    ]
    # A node's hives all go in its owner's Default, S2 included.
    assert rows(
        cursor,
        "SELECT a.id_sensore_fisico, ap.id_utente_proprietario FROM arnie a"
        " LEFT JOIN apiari ap USING (id_apiario) ORDER BY 1",
    ) == [("S1", 1), ("S2", 1), ("S3", 2), ("S4", None)]
    # User 2 keeps access to S1 and S2 as a role on user 1's Default: the
    # higher of read and write. User 3's revoked access is not revived.
    assert rows(
        cursor,
        "SELECT s.id_utente, ap.id_utente_proprietario, s.ruolo FROM utenti_apiari s"
        " JOIN apiari ap USING (id_apiario)",
    ) == [(2, 1, "collaborator")]
    assert rows(cursor, "SELECT to_regclass('utenti_arnie') IS NULL") == [(True,)]


def test_0005_downgrades_back_to_per_hive_access(before_0005):
    """Owners come back as 'admin' on each hive, shares as their level on each."""
    from alembic import command

    from meshbee_core.migrations import alembic_config

    cursor = before_0005
    upgrade(TEST_DB_URL, "0005", search_path=FROM_MIGRATIONS)

    command.downgrade(alembic_config(TEST_DB_URL, search_path=FROM_MIGRATIONS), "0004")

    assert rows(
        cursor,
        "SELECT ua.id_utente, a.id_sensore_fisico, ua.permessi FROM utenti_arnie ua"
        " JOIN arnie a USING (id_arnia) ORDER BY 1, 2",
    ) == [
        (1, "S1", "admin"),
        (1, "S2", "admin"),
        (2, "S1", "write"),
        (2, "S2", "write"),
        (2, "S3", "admin"),
    ]
    assert rows(cursor, "SELECT to_regclass('apiari') IS NULL") == [(True,)]
