"""SC2Pulse client package. Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use.

Client names are re-exported lazily so ``smurfsniper.api.sc2pulse.models`` and
``.ids`` can be imported without loading the HTTP transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smurfsniper.api.sc2pulse.client import (
        ATTRIBUTION,
        BASE_URL,
        SC2PulseClient,
        make_limiter,
    )

__all__ = ["ATTRIBUTION", "BASE_URL", "SC2PulseClient", "make_limiter"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from smurfsniper.api.sc2pulse import client

        return getattr(client, name)
    raise AttributeError(name)
