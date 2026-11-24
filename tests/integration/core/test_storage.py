"""
Files follow the transaction that records them (#3).

On a real session, because the hooks hang on the session's commit and rollback
events: a fake one would only prove that they were registered.
"""

from sqlalchemy import text

from meshbee_core.storage import delete_after_commit, discard_on_rollback


def write(session):
    """
    Run a statement, as the service does right after registering a hook: a
    session that has begun nothing has no transaction to roll back.
    """
    session.exec(text("SELECT 1"))


def test_a_new_file_is_removed_when_the_transaction_rolls_back(session, storage):
    """Otherwise every failed upload would leave an unreferenced file."""
    storage.save("arnie/1/new.webp", b"x")
    discard_on_rollback(session, storage, "arnie/1/new.webp")
    write(session)

    session.rollback()

    assert not storage.path("arnie/1/new.webp").exists()


def test_a_new_file_is_kept_when_the_transaction_commits(session, storage):
    storage.save("arnie/1/new.webp", b"x")
    discard_on_rollback(session, storage, "arnie/1/new.webp")
    write(session)

    session.commit()
    # A later transaction on the same session must not fire the stale hook.
    session.rollback()

    assert storage.path("arnie/1/new.webp").exists()


def test_a_replaced_file_stays_until_the_transaction_commits(session, storage):
    """
    Deleting it straight away would leave the row pointing at nothing if the
    transaction then failed.
    """
    storage.save("arnie/1/old.webp", b"x")
    delete_after_commit(session, storage, "arnie/1/old.webp")
    write(session)
    assert storage.path("arnie/1/old.webp").exists()

    session.commit()

    assert not storage.path("arnie/1/old.webp").exists()


def test_a_replaced_file_is_kept_when_the_transaction_rolls_back(session, storage):
    storage.save("arnie/1/old.webp", b"x")
    delete_after_commit(session, storage, "arnie/1/old.webp")
    write(session)

    session.rollback()
    session.commit()

    assert storage.path("arnie/1/old.webp").exists()


def test_a_rolled_back_savepoint_is_not_the_end_of_the_transaction(session, storage):
    """A nested SAVEPOINT failing inside the request must not discard the upload."""
    storage.save("arnie/1/new.webp", b"x")
    discard_on_rollback(session, storage, "arnie/1/new.webp")
    write(session)

    nested = session.begin_nested()
    nested.rollback()

    assert storage.path("arnie/1/new.webp").exists()
