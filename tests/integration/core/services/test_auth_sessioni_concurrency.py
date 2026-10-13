"""Two refreshes with one token, really at the same time (#16).

Unlike the rest of the integration tier, this does not run inside the rolled-back
test transaction: the race only exists between two connections that each commit,
so the rows here are committed and deleted again at the end.

A barrier holds both redeems right after they read the session row, so both have
seen it unrevoked before either writes. That is the interleaving that once let
both win; without the barrier the race would only show up now and then.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.rows import dict_row
from sqlmodel import Session

from meshbee_core.repository import sessioni
from meshbee_core.services import auth
from tests.conftest import TEST_DB_PARAMS

TIMEOUT = 10


@pytest.fixture
def committed(test_engine):
    """A raw autocommit cursor; the user it creates is deleted, with its sessions."""
    connection = psycopg.connect(**TEST_DB_PARAMS, autocommit=True)
    cursor = connection.cursor(row_factory=dict_row)
    created = []

    def make_utente():
        cursor.execute(
            """
            INSERT INTO utenti (email, password_hash, nome, cognome)
            VALUES (%s, 'x', 'Race', 'Test') RETURNING id_utente
            """,
            (f"race-{len(created)}@example.org",),
        )
        created.append(cursor.fetchone()["id_utente"])
        return created[-1]

    try:
        yield make_utente, cursor
    finally:
        # token_sessione rows go with the user (ON DELETE CASCADE).
        cursor.execute("DELETE FROM utenti WHERE id_utente = ANY(%s)", (created,))
        connection.close()


def in_own_transaction(test_engine, work):
    """Run `work(session)` the way get_session does: commit, or roll back."""
    with Session(test_engine, expire_on_commit=False) as session, session.begin():
        return work(session)


def test_two_concurrent_redeems_of_one_token_cannot_both_win(
    test_engine, committed, monkeypatch
):
    make_utente, cursor = committed
    id_utente = make_utente()
    in_own_transaction(
        test_engine, lambda s: auth.open_session(s, id_utente, "tok-1", 7)
    )

    both_have_read = threading.Barrier(2, timeout=TIMEOUT)
    read = sessioni.get_by_hash

    def read_then_wait(session, token_hash):
        row = read(session, token_hash)
        both_have_read.wait()
        return row

    monkeypatch.setattr(sessioni, "get_by_hash", read_then_wait)

    def redeem():
        return in_own_transaction(
            test_engine, lambda s: auth.redeem_refresh_token(s, "tok-1")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(redeem), pool.submit(redeem)]
        results = [future.result(timeout=TIMEOUT) for future in futures]

    winners = [user for user in results if user is not None]
    assert len(winners) == 1
    assert winners[0]["id_utente"] == id_utente

    # The loser is treated as a reuse: the token is spent for good.
    cursor.execute(
        "SELECT revocato FROM token_sessione WHERE id_utente = %s", (id_utente,)
    )
    assert [row["revocato"] for row in cursor.fetchall()] == [True]
