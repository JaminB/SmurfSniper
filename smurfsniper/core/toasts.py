"""The toast request type shared by the event bus producers and the HUD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["info", "success", "warning", "danger", "win", "loss"]


@dataclass(frozen=True)
class ToastSpec:
    title: str
    body: str | None = None
    kind: Kind = "info"
    accent: tuple[int, int, int] | None = None  # overrides the kind accent (e.g. race)
    id: str | None = None  # same id -> update in place (text + timer reset)
    duration_ms: int | None = None  # None -> config.overlays.toasts.seconds
    chip: str | None = None  # optional hotkey chip, e.g. "Ctrl+Shift+2"
