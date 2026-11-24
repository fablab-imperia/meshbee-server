"""
Uploads over HTTP (#3): where files go, and how big a request may be.

`get_storage` is a dependency so tests can point it at a temporary directory.
`BodySizeLimitMiddleware` refuses an oversized request body before anything
parses it: FastAPI reads a multipart form, files included, before any
dependency runs, so a size check in the route alone would come after the
whole upload had been spooled to disk.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status

from api.config import Settings, get_settings
from meshbee_core.limits import FOTO_MAX_BYTES
from meshbee_core.storage import LocalStorage, Storage

TOO_LARGE = f"File troppo grande: massimo {FOTO_MAX_BYTES // (1024 * 1024)} MB"

# Room for the multipart framing around a file of the largest accepted size.
# Every other body the API accepts is a small JSON document.
MAX_BODY_BYTES = FOTO_MAX_BYTES + 64 * 1024


@lru_cache
def local_storage(root: Path) -> LocalStorage:
    return LocalStorage(root)


def get_storage(config: Annotated[Settings, Depends(get_settings)]) -> Storage:
    return local_storage(config.STORAGE_DIR)


def too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=TOO_LARGE
    )


class BodySizeLimitMiddleware:
    """
    Answer 413 to a request whose body is over `max_bytes`.

    A declared Content-Length is refused before the body is read; a body with
    none (chunked) is counted as it arrives. Plain ASGI, like the reporting
    middleware in main.py.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit():
            if int(declared) > self.max_bytes:
                await self._refuse(send)
                return

        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the app, so its exception handling turns it
                    # into the 413 response (FastAPI re-raises HTTPException
                    # from body parsing as it is).
                    raise too_large()
            return message

        await self.app(scope, counting_receive, send)

    @staticmethod
    async def _refuse(send) -> None:
        body = json.dumps({"detail": TOO_LARGE}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status.HTTP_413_CONTENT_TOO_LARGE,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
