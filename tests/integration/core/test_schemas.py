"""Agreement between the pydantic models and the database schema.

The measurement rules are declared once, in meshbee_core/limits.py, and surface
three ways — as validators on the API shapes and as CHECK constraints on the
tables, both in meshbee_core/models.py, and as JSON Schema keywords in mqtt_handler/contract.py,
the copy strangers read. A database, though, only has the CHECKs its migrations
created. These tests derive their cases from the published contract and assert
that the schemas and the real database reject the same value, so a bound changed
without a revision fails here instead of in production.
"""
import re
from decimal import Decimal
from typing import get_args

import psycopg2
import pytest
from pydantic import ValidationError

from meshbee_core.models import ArniaBase, LetturaBase, Permesso, Ruolo, TipoAttivita
from mqtt_handler.contract import MqttPayload

# The MQTT contract publishes the ranges as JSON Schema keywords, for the
# consumers that never see this repository. Deriving the cases from it — rather
# than writing the numbers again here — tests what is actually published.
CONTRACT = MqttPayload.model_json_schema()
MEASUREMENTS = ("temperatura", "umidita", "peso", "bat")
# The contract names fields as the firmware sends them; LetturaBase uses the
# column name. Identity unless listed.
MODEL_FIELD = {"bat": "batteria"}
EPSILON = Decimal("0.01")


def contract_cases(*, inside: bool):
    """(model, field, value) at, or one step outside, each published bound."""
    for field in MEASUREMENTS:
        prop = CONTRACT["properties"][field]
        for keyword, direction in (("minimum", -1), ("maximum", 1)):
            if keyword not in prop:
                continue  # peso has no upper bound
            bound = Decimal(str(prop[keyword]))
            yield (
                LetturaBase,
                MODEL_FIELD.get(field, field),
                str(bound if inside else bound + direction * EPSILON),
            )


# (model, field, value just outside the allowed range)
OUT_OF_RANGE = [
    *contract_cases(inside=False),
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
    (LetturaBase, "batteria"): ("letture", "batteria"),
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
        *contract_cases(inside=True),
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


ID_COLUMNS = [
    ("id_nodo", "nodi", "id_nodo"),
    ("id_sensore", "arnie", "id_sensore_fisico"),
]


@pytest.mark.parametrize(
    "field, table, column", ID_COLUMNS, ids=[f for f, _, _ in ID_COLUMNS]
)
def test_the_contract_id_length_matches_the_column(db, field, table, column):
    """
    maxLength in the published contract is VARCHAR(50) in the database.

    No API shape bounds these, so the column is the only other copy —
    and an over-long id fails as a driver-level error, i.e. a 500, not a 422. A
    node told the wrong limit by the contract is a node that silently stops
    being ingested.
    """
    db.execute(
        """
        SELECT character_maximum_length AS length
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )

    assert db.fetchone()["length"] == CONTRACT["properties"][field]["maxLength"]


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
    The Literal in limits.py and the CHECK in the database list exactly the same values.

    Adding a value to one without the other either lets a request through that
    the database will reject with a 500, or blocks a value the schema allows.
    """
    assert set(get_args(literal)) == check_constraint_values(db, table, column)


def test_auth_ranks_exactly_the_permissions_the_schema_allows(db):
    """
    services.auth.PERMISSION_LEVELS, the Permesso literal and the CHECK all agree.

    A level present in the schema but missing from the map would raise a KeyError
    mid-request; one present only in the map would never be reachable.
    """
    from meshbee_core.services.auth import PERMISSION_LEVELS

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

    These are exactly the keys of PERMISSION_LEVELS in services/auth.py, so the
    "unknown permission" fallback there is unreachable through the schema.
    """
    utente, arnia = make_utente(), make_arnia()

    with pytest.raises(psycopg2.errors.CheckViolation):
        grant_access(utente["id_utente"], arnia["id_arnia"], "superuser")
