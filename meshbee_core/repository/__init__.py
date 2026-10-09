"""Persistence only: tables and queries, no business rules.

Every function takes the session as its first argument and never opens one —
the caller owns the transaction lifecycle. Functions that write `flush()`, so a
constraint violation surfaces inside the caller's `integrity_errors` block and
generated values (ids, server defaults) are available straight away.

Results are plain dicts, not model instances: what leaves this layer is data,
detached from the session that produced it.
"""

from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from meshbee_core.paging import Page, Paging


def as_dict(
    obj: SQLModel | None, *, only: Iterable[str] = None, exclude: Iterable[str] = ()
) -> dict[str, Any] | None:
    """
    A table row as a dict of its columns, or None for no row.

    Reads through `getattr` rather than `model_dump()`: a column the database
    computed during the flush (a `func.now()`, a server default) is expired on
    the instance, and only attribute access loads it back.
    """
    if obj is None:
        return None
    names = [column.name for column in obj.__table__.columns]
    if only is not None:
        names = [name for name in names if name in set(only)]
    return {name: getattr(obj, name) for name in names if name not in set(exclude)}


def as_dicts(rows) -> list:
    """`as_dict` over a result of whole rows."""
    return [as_dict(row) for row in rows]


def mapping(row) -> dict[str, Any] | None:
    """A result row of individual columns as a dict, or None for no row."""
    return dict(row._mapping) if row is not None else None


def fetch_page(
    session: Session,
    query,
    paging: Paging,
    to_items: Callable[[list], list[dict[str, Any]]] = as_dicts,
) -> Page:
    """
    One window of an ordered query, as `to_items` turns its rows into dicts.

    The query's ORDER BY must end on a unique column, or rows that tie could
    repeat on one page and be skipped on the next. The total counts the query
    without its order and window, and only when `paging.total` asks for it.
    """
    window = query.offset(paging.offset or None).limit(paging.limit)
    items = to_items(session.exec(window).all())
    total = None
    if paging.total:
        counted = select(func.count()).select_from(query.order_by(None).subquery())
        total = session.exec(counted).one()
    return Page(items, total)
