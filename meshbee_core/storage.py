"""
Where uploaded files live (#3), behind one small interface.

A row in `allegati` names its file by a key (`arnie/7/3f2a….webp`); a `Storage`
turns keys into bytes. `LocalStorage` keeps them in a directory, which compose
mounts from the host. Another backend (object storage) only has to implement
the same three methods.

Files are not transactional, so the services tie them to the session they write
the row in:

- a new file is written before the row, and removed again if the transaction
  rolls back (`discard_on_rollback`);
- a replaced file is removed only once the transaction has committed
  (`delete_after_commit`), so a failed request never leaves a row pointing at a
  file that is gone.

What can still go wrong is a crash between commit and delete, which leaves an
unreferenced file behind: wasted space, never a broken photo.
"""

import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from sqlalchemy import event
from sqlmodel import Session

logger = logging.getLogger(__name__)


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> None:
        """Store `data` under `key`, replacing nothing: keys are never reused."""

    def path(self, key: str) -> Path:
        """The local file holding `key`'s bytes, to serve it from."""

    def delete(self, key: str) -> None:
        """Remove `key`; one that is already gone is not an error."""


class LocalStorage:
    """Files under one directory, each key a relative path inside it."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path(self, key: str) -> Path:
        """
        Raises:
            ValueError: if the key is absolute, climbs out with `..`, or is empty.
        """
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or ".." in parts or "\\" in key:
            raise ValueError(f"Invalid storage key: {key!r}")
        return self.root.joinpath(*parts)

    def save(self, key: str, data: bytes) -> None:
        """
        Atomic: written to a temporary file next to the target, then renamed
        over it, so a reader never sees half a file.
        """
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def is_writable(self) -> bool:
        """Whether files can be created here, for a warning at startup."""
        return self.root.is_dir() and os.access(self.root, os.W_OK | os.X_OK)


def _delete_quietly(storage: Storage, key: str) -> None:
    # After the transaction has ended there is nobody left to raise to: a file
    # that could not be removed is only wasted space, so it is logged.
    try:
        storage.delete(key)
    except Exception:
        logger.exception(f"Impossibile eliminare il file {key}")


def _on_outcome(session: Session, *, commit=None, rollback=None) -> None:
    """
    Run one of two callbacks when the session's current transaction ends.

    Only the first outcome counts: a session reused for another transaction
    afterwards must not fire a stale callback. A rollback of a nested SAVEPOINT
    is not the outcome, so it is ignored.
    """
    ended = False

    def committed(_session):
        nonlocal ended
        if not ended:
            ended = True
            if commit:
                commit()

    def rolled_back(_session, previous_transaction):
        nonlocal ended
        if not ended and not previous_transaction.nested:
            ended = True
            if rollback:
                rollback()

    event.listen(session, "after_commit", committed)
    event.listen(session, "after_soft_rollback", rolled_back)


def discard_on_rollback(session: Session, storage: Storage, key: str) -> None:
    """Remove a newly written file if the session's transaction rolls back."""
    _on_outcome(session, rollback=lambda: _delete_quietly(storage, key))


def delete_after_commit(session: Session, storage: Storage, key: str) -> None:
    """Remove a file once the session's transaction has committed, not before."""
    _on_outcome(session, commit=lambda: _delete_quietly(storage, key))
