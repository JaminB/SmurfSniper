"""Local StarCraft II client API (``/game``, ``/ui``).

The client is re-exported lazily so the models import without httpx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from smurfsniper.api.sc2client.models import GameInfo, GamePlayer, UiInfo, race_code

if TYPE_CHECKING:
    from smurfsniper.api.sc2client.client import DEFAULT_URL, LocalSc2Client, normalize_base_url

__all__ = [
    "DEFAULT_URL",
    "GameInfo",
    "GamePlayer",
    "LocalSc2Client",
    "UiInfo",
    "normalize_base_url",
    "race_code",
]
_LAZY = {"DEFAULT_URL", "LocalSc2Client", "normalize_base_url"}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from smurfsniper.api.sc2client import client

        return getattr(client, name)
    raise AttributeError(name)
