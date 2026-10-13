"""Tests for the in-memory request limit (api/ratelimit.py), on a fake clock."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.ratelimit import SlidingWindowLimiter, enforce


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def limiter(clock):
    return SlidingWindowLimiter(limit=3, window=60, clock=clock)


def test_hits_up_to_the_limit_are_allowed(limiter):
    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]


def test_the_next_hit_is_told_how_long_to_wait(limiter, clock):
    limiter.hit("a")
    clock.now += 20
    limiter.hit("a")
    limiter.hit("a")

    assert limiter.hit("a") == pytest.approx(40)


def test_the_window_slides(limiter, clock):
    for _ in range(3):
        limiter.hit("a")
    clock.now += 60

    assert limiter.hit("a") is None


def test_a_refused_hit_is_not_counted(limiter, clock):
    """A client that waits gets back in, however often it was refused meanwhile."""
    for _ in range(3):
        limiter.hit("a")
    for _ in range(5):
        limiter.hit("a")
    clock.now += 60

    assert limiter.hit("a") is None


def test_keys_are_counted_apart(limiter):
    for _ in range(3):
        limiter.hit("a")

    assert limiter.hit("b") is None


def test_clear_forgets_everything(limiter):
    for _ in range(3):
        limiter.hit("a")
    limiter.clear()

    assert limiter.hit("a") is None


def test_idle_keys_are_dropped_past_the_tracking_cap(limiter, clock, monkeypatch):
    monkeypatch.setattr("api.ratelimit.MAX_TRACKED", 2)
    limiter.hit("a")
    limiter.hit("b")
    clock.now += 61

    limiter.hit("c")

    assert set(limiter._hits) == {"c"}


def request_from(host):
    return Request({"type": "http", "client": (host, 1234) if host else None})


def test_enforce_raises_429_with_retry_after(limiter):
    for _ in range(3):
        enforce(limiter, request_from("10.0.0.1"))

    with pytest.raises(HTTPException) as exc_info:
        enforce(limiter, request_from("10.0.0.1"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"


def test_enforce_keys_on_the_client_address(limiter):
    for _ in range(3):
        enforce(limiter, request_from("10.0.0.1"))

    enforce(limiter, request_from("10.0.0.2"))


def test_a_request_without_a_client_address_is_still_counted(limiter):
    for _ in range(3):
        enforce(limiter, request_from(None))

    with pytest.raises(HTTPException):
        enforce(limiter, request_from(None))
