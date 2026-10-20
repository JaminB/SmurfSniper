"""Gating for pro / external lookups (Aligulac, Liquipedia)."""

from __future__ import annotations

import re
from typing import Protocol

from smurfsniper.api.sc2pulse.ids import LinkType
from smurfsniper.api.sc2pulse.models import Character, ProPlayerEntry

MIN_NAME_LEN = 4
MAX_CANDIDATES = 3
_BARCODE = re.compile(r"^[Il|]+$")
_ALIGULAC_URL = re.compile(r"aligulac\.com/players/(\d+)")


class IdentityLike(Protocol):
    character: Character
    pro: ProPlayerEntry | None
    exact_matches: int


def is_distinctive_name(name: str, candidates_count: int) -> bool:
    """A name is worth an external lookup when it is long, not a barcode, and rare."""
    base = name.split("#")[0].strip()
    if len(base) < MIN_NAME_LEN or _BARCODE.match(base):
        return False
    return candidates_count <= MAX_CANDIDATES


def should_query_pro_sources(identity: IdentityLike) -> bool:
    if identity.pro is not None:
        return True
    return is_distinctive_name(identity.character.name, identity.exact_matches)


def aligulac_id(identity: IdentityLike, pro: ProPlayerEntry | None = None) -> int | None:
    """Aligulac id from the SC2Pulse pro record or its ALIGULAC link."""
    for entry in (pro, identity.pro):
        if entry is None:
            continue
        if entry.pro_player.aligulac_id:
            return entry.pro_player.aligulac_id
        for link in entry.links:
            if link.type == LinkType.ALIGULAC:
                m = _ALIGULAC_URL.search(link.url)
                if m:
                    return int(m.group(1))
    return None
