"""Tiny text helpers shared by ``core`` and ``ui`` (no Qt, no project imports)."""

from __future__ import annotations

from collections.abc import Sequence

RACE_LABEL = {"TERRAN": "Terran", "PROTOSS": "Protoss", "ZERG": "Zerg", "RANDOM": "Random"}
SEP = " · "


def join(parts: Sequence[str | None], sep: str = SEP) -> str | None:
    """Join the non-empty parts; None if there are none."""
    kept = [p for p in parts if p]
    return sep.join(kept) if kept else None


def duration(seconds: int | None) -> str | None:
    """``680`` -> ``11:20``."""
    if not seconds or seconds <= 0:
        return None
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
