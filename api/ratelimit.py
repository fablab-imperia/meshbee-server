"""A per-client request limit for anonymous routes that cost something.

The forgot-password route can send an email on every call, and a provider's
daily cap (100 a day on Resend's free tier) is easy to exhaust. This counts the
requests each client address made over a sliding window, in memory.

In memory means per API process: the count starts over on a restart, and
several uvicorn workers would each keep their own. That is enough for one
container with one worker, as deployed. The per-account cap, which matters
more, lives in the database (`services/password_reset.py`) and holds across both.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

# Past this many tracked addresses, the idle ones are dropped on the next hit.
MAX_TRACKED = 10_000


class SlidingWindowLimiter:
    """At most `limit` hits per key within any `window` seconds."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        # Routes are plain `def`, so they run concurrently in the threadpool.
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """
        Count one request from `key`; None if allowed, else seconds until it would be.

        A refused request is not counted, so a client that waits is let back in.
        """
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return hits[0] + self.window - now
            hits.append(now)
            if len(self._hits) > MAX_TRACKED:
                self._forget_idle(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _forget_idle(self, now: float) -> None:
        idle = [k for k, hits in self._hits.items() if hits[-1] <= now - self.window]
        for key in idle:
            del self._hits[key]


def enforce(limiter: SlidingWindowLimiter, request: Request) -> None:
    """Raise 429 with Retry-After when the client has used up its requests."""
    # The address uvicorn resolved from Caddy's X-Forwarded-For (see README.md).
    key = request.client.host if request.client else "unknown"
    wait = limiter.hit(key)
    if wait is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Troppe richieste: riprova più tardi",
            headers={"Retry-After": str(max(1, round(wait)))},
        )
