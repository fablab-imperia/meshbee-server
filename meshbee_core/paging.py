"""Optional paging of list queries: which window of a list, and its total."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Paging:
    """
    A window over a list: skip `offset` rows, return at most `limit`.

    The default is the whole list. `total` asks for the size of the whole list
    too, which costs a COUNT query, so callers ask only when they show it.
    """

    limit: int | None = None
    offset: int = 0
    total: bool = False


EVERYTHING = Paging()


@dataclass(frozen=True)
class Page:
    """The rows of one window, and the whole list's size when it was asked for."""

    items: list[dict[str, Any]]
    total: int | None = None
