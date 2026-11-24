"""
Stored files (#3), whatever they are attached to.

What a file is attached to is the caller's business: the hive photo goes
through `services/arnie.py`, which only decides the key prefix and which
column points at the file. A user's profile photo would do the same.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

from meshbee_core.errors import NotFound
from meshbee_core.images import process_photo
from meshbee_core.repository import allegati
from meshbee_core.storage import Storage, delete_after_commit, discard_on_rollback

NOT_FOUND = "File non trovato"


def store_image(
    session, storage: Storage, data: bytes, prefix: str, id_utente: int | None
) -> dict[str, Any]:
    """
    Process an uploaded image, store it and record it.

    The key is new every time, under `prefix`: a file is never overwritten, so
    a client still downloading the previous photo gets the previous photo.

    Raises:
        InvalidData: if the bytes are not an accepted image.
    """
    image = process_photo(data)
    chiave = f"{prefix}/{uuid4().hex}.{image.extension}"
    storage.save(chiave, image.data)
    discard_on_rollback(session, storage, chiave)
    return allegati.insert(
        session,
        chiave=chiave,
        content_type=image.content_type,
        dimensione=len(image.data),
        larghezza=image.width,
        altezza=image.height,
        id_utente_caricamento=id_utente,
    )


def remove(session, storage: Storage, id_allegato: int) -> None:
    """Delete the record now and the file once the transaction commits."""
    row = allegati.delete(session, id_allegato)
    if row is not None:
        delete_after_commit(session, storage, row["chiave"])


def locate(session, storage: Storage, id_allegato: int) -> dict[str, Any]:
    """
    The file behind an attachment: its record plus `path`, to serve it from.

    Raises:
        NotFound: if the record or its file is gone.
    """
    row = allegati.get(session, id_allegato)
    if row is None:
        raise NotFound(NOT_FOUND)
    path: Path = storage.path(row["chiave"])
    if not path.is_file():
        raise NotFound(NOT_FOUND)
    return {**row, "path": path}
