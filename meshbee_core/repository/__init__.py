"""Persistence only: tables and queries, no business rules.

Every function takes the session as its first argument and never opens one —
the caller owns the transaction lifecycle. Functions that write `flush()`, so a
constraint violation surfaces inside the caller's `integrity_errors` block and
generated values (ids, server defaults) are available straight away.

Results are plain dicts, not model instances: what leaves this layer is data,
detached from the session that produced it.
"""
from typing import Any, Dict, Iterable, Optional

from sqlmodel import SQLModel


def as_dict(obj: Optional[SQLModel], *, only: Iterable[str] = None,
            exclude: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
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


def mapping(row) -> Optional[Dict[str, Any]]:
    """A result row of individual columns as a dict, or None for no row."""
    return dict(row._mapping) if row is not None else None
