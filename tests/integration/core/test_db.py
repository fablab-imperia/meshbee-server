"""Tests for the engine meshbee_core.db builds (meshbee_core/db.py)."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from meshbee_core import db as core_db
from meshbee_core.models import Utente
from tests.conftest import TEST_DB_PARAMS

HASH = "$2b$12$not-for-the-logs"


@pytest.fixture
def engine(build_core_settings, test_schema):
    """The production engine, pointed at postgres-test."""
    core_db.init_db_pool(
        build_core_settings(
            DB_HOST=TEST_DB_PARAMS["host"],
            DB_PORT=TEST_DB_PARAMS["port"],
            DB_NAME=TEST_DB_PARAMS["dbname"],
            DB_USER=TEST_DB_PARAMS["user"],
            DB_PASSWORD=TEST_DB_PARAMS["password"],
        ),
        maxconn=1,
    )
    yield core_db.engine
    core_db.close_db_pool()


def utente():
    return Utente(email="dup@example.org", password_hash=HASH, nome="a", cognome="b")


def test_a_database_error_does_not_carry_the_values_it_was_given(engine):
    """
    Bound parameters stay out of exception text, and so out of every log line.

    Every layer that catches a database error logs it with `{e}`. SQLAlchemy
    appends the statement's parameters to that text by default, which for an
    INSERT INTO utenti means the password hash and the email.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        session.add(utente())
        session.flush()
        session.add(utente())

        with pytest.raises(IntegrityError) as exc_info:
            session.flush()

        session.close()
        transaction.rollback()

    assert HASH not in str(exc_info.value)
