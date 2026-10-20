"""API client layer: one package per external service plus a shared transport.

``Clients`` and ``build_clients`` are re-exported lazily so that importing a models
module (for example ``smurfsniper.api.sc2pulse.models``) does not pull in httpx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smurfsniper.api.registry import Clients, build_clients

__all__ = ["Clients", "build_clients"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from smurfsniper.api import registry

        return getattr(registry, name)
    raise AttributeError(name)
