"""Query-string building shared by every client."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Enum):
        if getattr(type(value), "__param_by_name__", False):
            return value.name
        return _scalar(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def build_params(**kw: Any) -> list[tuple[str, str]]:
    """Encode keyword arguments as an ordered list of query pairs.

    - ``None`` values are dropped.
    - Lists, tuples, sets and frozensets become repeated keys (``?a=1&a=2``), never a
      comma-joined value.
    - ``bool`` becomes ``"true"``/``"false"``; ``datetime`` ISO-8601 UTC with ``Z``.
    - ``Enum`` becomes ``.value``, or ``.name`` if the enum class sets
      ``__param_by_name__ = True``.

    Keys keep insertion order. A trailing underscore is stripped so reserved words can
    be passed (``from_=...`` gives ``from``).
    """
    out: list[tuple[str, str]] = []
    for key, value in kw.items():
        if value is None:
            continue
        name = key[:-1] if key.endswith("_") else key
        if isinstance(value, list | tuple | set | frozenset):
            out.extend((name, _scalar(v)) for v in value if v is not None)
        else:
            out.append((name, _scalar(value)))
    return out
