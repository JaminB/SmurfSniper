"""Cross-network identity lookups for distinctive opponent handles.

SC2Pulse already surfaces external links for *revealed pros*. This module covers
the rest: when an opponent's in-game name is distinctive enough to be worth a web
lookup, it pulls real data from public, key-free sources (Aligulac, Liquipedia)
and constructs candidate same-handle profile URLs on other game/streaming networks.

Everything here is defensive: every fetch swallows failures and returns ``None`` /
``[]`` so a flaky network never raises into the Ctrl+F2 hotkey path. Two pooled
``httpx.Client``s (one per host) are reused across the process; SC2Pulse's client
is base-url-bound and is not reused here.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

import httpx

from smurfsniper.api import sc2pulse
from smurfsniper.logger import logger

ALIGULAC_BASE = "http://aligulac.com"
LIQUIPEDIA_BASE = "https://liquipedia.net"
TIMEOUT = 12.0

# Aligulac's REST API requires a (free) key. Set it from config via
# ``set_aligulac_api_key``; without it that source is skipped silently. Get one
# at http://aligulac.com/about/api/.
_aligulac_api_key: str = ""

# Liquipedia API ToS require a descriptive, contactable User-Agent.
USER_AGENT = "smurfsniper/0.1 (SC2 overlay; https://github.com/JaminB/smurfsniper)"

# A name is "distinctive" only if SC2Pulse returns at most this many accounts whose
# base name exactly matches — more than that means the handle is common.
_MAX_EXACT_CANDIDATES = 3
_MIN_NAME_LEN = 4
# Characters barcodes are built from (visually identical verticals).
_BARCODE_CHARS = set("il1|")

_aligulac_client: Optional[httpx.Client] = None
_liquipedia_client: Optional[httpx.Client] = None


def _client(which: str) -> httpx.Client:
    global _aligulac_client, _liquipedia_client
    if which == "aligulac":
        if _aligulac_client is None:
            _aligulac_client = httpx.Client(
                base_url=ALIGULAC_BASE, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
        return _aligulac_client
    if _liquipedia_client is None:
        _liquipedia_client = httpx.Client(
            base_url=LIQUIPEDIA_BASE, timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _liquipedia_client


def set_aligulac_api_key(key: Optional[str]) -> None:
    """Set the Aligulac API key (from config). Empty/None disables Aligulac."""
    global _aligulac_api_key
    _aligulac_api_key = (key or "").strip()


def close() -> None:
    """Close pooled clients (e.g. on shutdown). Safe to call repeatedly."""
    global _aligulac_client, _liquipedia_client
    for c in (_aligulac_client, _liquipedia_client):
        if c is not None:
            c.close()
    _aligulac_client = None
    _liquipedia_client = None


def _base_name(name: str) -> str:
    """In-game handle without the ``#1234`` discriminator, trimmed + casefolded."""
    return name.split("#")[0].strip().casefold()


def is_distinctive_name(name: str) -> bool:
    """True when ``name`` is unusual enough to be worth a cross-network lookup.

    Rejects short names, barcodes (all chars from ``il1|``), all-same-char and
    all-digit handles, then checks SC2Pulse: a name shared by many accounts is
    common, not distinctive.
    """
    base = _base_name(name)
    if len(base) < _MIN_NAME_LEN:
        return False
    if base.isdigit():
        return False
    if len(set(base)) == 1:
        return False
    if set(base) <= _BARCODE_CHARS:
        return False

    try:
        candidates = sc2pulse.search_characters(name)
    except sc2pulse.SC2PulseError as exc:
        logger.warning(f"Distinctiveness check failed for {name!r}: {exc}")
        return False

    exact = 0
    for entry in candidates:
        member = entry.get("members") if isinstance(entry, dict) else None
        char = member.get("character") if isinstance(member, dict) else None
        cand_name = char.get("name") if isinstance(char, dict) else None
        if cand_name and _base_name(cand_name) == base:
            exact += 1
    return 0 < exact <= _MAX_EXACT_CANDIDATES


def aligulac_player(name: str) -> Optional[dict]:
    """Look up a player on Aligulac by exact (casefold) tag match.

    Returns ``{name, country, race, profile_url}`` for the first matching player,
    or ``None``. Requires an Aligulac API key set via ``set_aligulac_api_key``;
    without it the lookup is skipped (returns ``None``).
    """
    key = _aligulac_api_key
    if not key:
        logger.debug("Aligulac lookup skipped: no API key configured.")
        return None

    base = _base_name(name)
    try:
        resp = _client("aligulac").get(
            "/api/v1/player/",
            params={
                "tag__iexact": name.split("#")[0].strip(),
                "apikey": key,
                "format": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"Aligulac lookup failed for {name!r}: {exc}")
        return None

    for obj in data.get("objects", []) if isinstance(data, dict) else []:
        tag = obj.get("tag")
        if not tag or tag.strip().casefold() != base:
            continue
        pid = obj.get("id")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", tag).strip("-")
        return {
            "name": obj.get("name") or None,
            "country": obj.get("country") or None,
            "race": obj.get("race") or None,
            "profile_url": f"{ALIGULAC_BASE}/players/{pid}-{slug}/" if pid else None,
        }
    return None


def liquipedia_page(name: str) -> Optional[Tuple[str, str]]:
    """Search the StarCraft2 Liquipedia wiki via opensearch.

    Returns ``(title, url)`` of the first hit whose title casefold-matches the
    base name, else ``None``.
    """
    base = _base_name(name)
    query = name.split("#")[0].strip()
    try:
        resp = _client("liquipedia").get(
            "/starcraft2/api.php",
            params={
                "action": "opensearch",
                "format": "json",
                "search": query,
                "limit": 5,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"Liquipedia lookup failed for {name!r}: {exc}")
        return None

    # opensearch shape: [term, [titles], [descriptions], [urls]]
    if not (isinstance(data, list) and len(data) >= 4):
        return None
    titles, urls = data[1], data[3]
    for title, url in zip(titles, urls):
        if title and url and title.strip().casefold() == base:
            return title, url
    # fall back to first hit if no exact title match
    if titles and urls:
        return titles[0], urls[0]
    return None


def twitch_live(character_id: int) -> Optional[dict]:
    """Return ``{title, url}`` if SC2Pulse lists this character live on Twitch.

    Reuses the cached ``sc2pulse.streams()`` list (no new key). Returns ``None``
    when the player is not currently streaming an identified SC2 stream.
    """
    try:
        streams = sc2pulse.streams()
    except sc2pulse.SC2PulseError as exc:
        logger.warning(f"Twitch-live lookup failed: {exc}")
        return None

    for entry in streams:
        if not isinstance(entry, dict):
            continue
        char = entry.get("character") or {}
        if char.get("id") != character_id:
            continue
        stream = entry.get("stream") or {}
        url = stream.get("url") or stream.get("profileImageUrl")
        title = stream.get("title")
        if url:
            return {"title": title or None, "url": url}
    return None


def candidate_handle_urls(name: str) -> Dict[str, str]:
    """Build same-handle profile URLs on other networks (unverified guesses)."""
    handle = re.sub(r"\s+", "", name.split("#")[0].strip())
    if not handle:
        return {}
    return {
        "Twitch": f"https://twitch.tv/{handle}",
        "YouTube": f"https://youtube.com/@{handle}",
        "X": f"https://x.com/{handle}",
        "Steam": f"https://steamcommunity.com/id/{handle}",
    }
