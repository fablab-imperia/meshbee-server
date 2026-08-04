"""Agreement between the pydantic models and the database schema.

The same rules are written twice — as Field bounds / validators in models.py and
as CHECK constraints in database/init.sql — with nothing linking them. These
tests assert both halves reject the same value, so widening one without the
other fails here instead of in production.
"""
import re
from typing import get_args

import psycopg2
import pytest
from pydantic import ValidationError

from api.models import ArniaBase, LetturaBase, Permesso, Ruolo, TipoAttivita

# (model, field, value just outside the allowed range)
OUT_OF_RANGE = [
    (LetturaBase, "temperatura", "-50.01"),
    (LetturaBase, "temperatura", "100.01"),
    (LetturaBase, "umidita", "-0.01"),
    (LetturaBase, "umidita", "100.01"),
    (LetturaBase, "peso", "-0.01"),
    (ArniaBase, "latitudine", "-90.01"),
    (ArniaBase, "latitudine", "90.01"),
    (ArniaBase, "longitudine", "-180.01"),
    (ArniaBase, "longitudine", "180.01"),
]

# Which table/column each model field maps to.
COLUMN = {
    (LetturaBase, "temperatura"): ("letture", "temperatura"),
    (LetturaBase, "umidita"): ("letture", "umidita"),
    (LetturaBase, "peso"): ("letture", "peso"),
    (ArniaBase, "latitudine"): ("arnie", "latitudine"),
    (ArniaBase, "longitudine"): ("arnie", "longitudine"),
}


@pytest.fixture
def arnia_row(db, make_arnia):
    """An arnia to hang letture off."""
    return make_arnia()


def insert_value(db, arnia_row, table, column, value):
    """Insert a single value into the given column, letting the DB validate it."""
    if table == "letture":
        db.execute(
            f"INSERT INTO letture (id_arnia, id_nodo, {column}) VALUES (%s, %s, %s)",
            (arnia_row["id_arnia"], arnia_row["id_nodo"], value),
        )
    else:
        db.execute(
            f"INSERT INTO arnie (id_nodo, id_sensore_fisico, {column}) VALUES (%s, %s, %s)",
            (arnia_row["id_nodo"], "SENSOR-BOUNDS", value),
        )


@pytest.mark.parametrize(
    "model, field, value",
    OUT_OF_RANGE,
    ids=[f"{f}={v}" for _, f, v in OUT_OF_RANGE],
)
def test_model_and_schema_reject_the_same_value(db, arnia_row, model, field, value):
    """A value the model refuses is also refused by the CHECK constraint."""
    table, column = COLUMN[(model, field)]

    with pytest.raises(ValidationError):
        model(**{field: value, **required_fields(model)})

    with pytest.raises(psycopg2.errors.CheckViolation):
        insert_value(db, arnia_row, table, column, value)


@pytest.mark.parametrize(
    "model, field, value",
    [
        (LetturaBase, "temperatura", "-50"),
        (LetturaBase, "temperatura", "100"),
        (LetturaBase, "umidita", "0"),
        (LetturaBase, "umidita", "100"),
        (LetturaBase, "peso", "0"),
        (ArniaBase, "latitudine", "-90"),
        (ArniaBase, "latitudine", "90"),
        (ArniaBase, "longitudine", "-180"),
        (ArniaBase, "longitudine", "180"),
    ],
)
def test_model_and_schema_accept_the_same_boundary(db, arnia_row, model, field, value):
    """The inclusive boundary is accepted on both sides."""
    table, column = COLUMN[(model, field)]

    model(**{field: value, **required_fields(model)})
    insert_value(db, arnia_row, table, column, value)


def required_fields(model):
    """The non-defaulted fields each model needs before it will construct."""
    if model is ArniaBase:
        return {"id_nodo": "NODE001", "id_sensore_fisico": "SENSOR01"}
    return {}


ENUM_FIELDS = [
    (Ruolo, "utenti", "ruolo"),
    (Permesso, "utenti_arnie", "permessi"),
    (TipoAttivita, "log_attivita", "tipo_attivita"),
]


def check_constraint_values(db, table, column):
    """The value set of the CHECK constraint governing `table.column`."""
    db.execute(
        """
        SELECT pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'c'
        """,
        (table,),
    )
    for row in db.fetchall():
        # Postgres renders `col IN (...)` as `(col)::text = ANY (ARRAY[...])`.
        if f"({column})::text = ANY" in row["definition"]:
            return set(re.findall(r"'([^']+)'::character varying", row["definition"]))
    raise AssertionError(f"no CHECK constraint found on {table}.{column}")


@pytest.mark.parametrize(
    "literal, table, column", ENUM_FIELDS, ids=[f"{t}.{c}" for _, t, c in ENUM_FIELDS]
)
def test_model_literals_match_the_schema_check(db, literal, table, column):
    """
    The Literal in models.py and the CHECK in init.sql list exactly the same values.

    Adding a value to one without the other either lets a request through that
    the database will reject with a 500, or blocks a value the schema allows.
    """
    assert set(get_args(literal)) == check_constraint_values(db, table, column)


def test_auth_ranks_exactly_the_permissions_the_schema_allows(db):
    """
    auth.PERMISSION_LEVELS, the Permesso literal and the CHECK all agree.

    A level present in the schema but missing from the map would raise a KeyError
    mid-request; one present only in the map would never be reachable.
    """
    from api.auth import PERMISSION_LEVELS

    schema_values = check_constraint_values(db, "utenti_arnie", "permessi")

    assert set(PERMISSION_LEVELS) == schema_values == set(get_args(Permesso))


def test_ruolo_values_accepted_by_the_schema(db, make_utente):
    """
    `utenti.ruolo` is CHECK (ruolo IN ('user','admin')) — 'utente' is not valid.

    The Italian domain naming applies to tables and columns, not to this value.
    """
    assert make_utente(ruolo="user")["ruolo"] == "user"
    assert make_utente(ruolo="admin")["ruolo"] == "admin"

    with pytest.raises(psycopg2.errors.CheckViolation):
        make_utente(ruolo="utente")


def test_permessi_values_accepted_by_the_schema(db, make_utente, make_arnia, grant_access):
    """
    `utenti_arnie.permessi` is CHECK (permessi IN ('read','write','admin')).

    These are exactly the keys of the permission_levels map in auth.py, so the
    "unknown permission" fallback there is unreachable through the schema.
    """
    utente, arnia = make_utente(), make_arnia()

    with pytest.raises(psycopg2.errors.CheckViolation):
        grant_access(utente["id_utente"], arnia["id_arnia"], "superuser")
