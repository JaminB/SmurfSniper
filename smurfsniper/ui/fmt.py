"""Pure text formatting for the HUD. Every helper returns None when it has nothing to say.

No widget code here, so the "never render placeholder text" rule can be unit tested
without Qt.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.matches import RecentResult
from smurfsniper.api.sc2pulse.ids import League

RACE_LABEL = {"TERRAN": "Terran", "PROTOSS": "Protoss", "ZERG": "Zerg", "RANDOM": "Random"}
RACE_INITIAL = {"TERRAN": "T", "PROTOSS": "P", "ZERG": "Z", "RANDOM": "R"}
RECORD_WINDOWS = ("3d", "7d", "30d", "season")
SEP = " · "


def join(parts: Sequence[str | None], sep: str = SEP) -> str | None:
    """Join the non-empty parts; None if there are none."""
    kept = [p for p in parts if p]
    return sep.join(kept) if kept else None


def league_label(league: int | None, tier: int | None = None, *, short: bool = False) -> str | None:
    """``Diamond 2``; Grandmaster has no tiers (``GM`` when ``short``)."""
    if league is None:
        return None
    try:
        lg = League(league)
    except ValueError:
        return None
    if lg is League.GRANDMASTER:
        return "GM" if short else "Grandmaster"
    name = lg.label
    return f"{name} {tier + 1}" if tier is not None and 0 <= tier <= 2 else name


def top_percent(region_percentile: float | None) -> str | None:
    """Region percentile (higher is better) -> ``top 9%`` / ``top 0.4%``."""
    if region_percentile is None:
        return None
    top = max(0.0, 100.0 - region_percentile)
    if top >= 50:
        return None  # "top 73%" is noise
    if top < 1:
        return f"top {max(top, 0.1):.1f}%"
    return f"top {top:.0f}%"


def mmr(value: int | None) -> str | None:
    return f"{value:,} MMR" if value else None


def duration(seconds: int | None) -> str | None:
    """``680`` -> ``11:20``."""
    if not seconds or seconds <= 0:
        return None
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def record_text(r: Record | None) -> str | None:
    """``9-1``; None for a window with no games (never ``0-0``)."""
    if r is None or r.games <= 0:
        return None
    return str(r)


def records_line(records: Mapping[str, Record], *, limit: int = 2) -> str | None:
    """``3d 9-1 · 7d 15-3``: the first ``limit`` windows that have games."""
    parts = []
    for key in RECORD_WINDOWS:
        text = record_text(records.get(key))
        if text:
            parts.append(f"{key} {text}")
        if len(parts) >= limit:
            break
    return join(parts)


def h2h_record(wins: int, losses: int, ties: int = 0) -> str | None:
    if wins + losses + ties <= 0:
        return None
    return f"{wins}-{losses}" + (f"-{ties}" if ties else "")


def vs_race(recent: Sequence[RecentResult], race: str | None, *, min_games: int = 3) -> str | None:
    """Winrate against ``race`` in recent games: ``vs Z 64%``."""
    if not race or race not in RACE_INITIAL or race == "RANDOM":
        return None
    games = [r for r in recent if r.opponent_race == race]
    if len(games) < min_games:
        return None
    wins = sum(1 for r in games if r.won)
    return f"vs {RACE_INITIAL[race]} {wins / len(games):.0%}"


def form(recent: Sequence[RecentResult], n: int = 5) -> list[bool]:
    """Newest-first wins/losses for the form strip."""
    return [r.won for r in recent[:n]]


def top_maps(maps: Mapping[str, Record], n: int = 3) -> str | None:
    return join([f"{name} {rec}" for name, rec in list(maps.items())[:n] if rec.games])


def flag(country: str | None) -> str | None:
    """ISO 3166 alpha-2 -> regional-indicator flag emoji."""
    if not country or len(country) != 2 or not country.isalpha():
        return None
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper())


def country(code: str | None, *, emoji: bool | None = None) -> str | None:
    """Flag emoji where the platform draws them; Windows has no flag glyphs, so the code."""
    if emoji is None:
        emoji = sys.platform != "win32"
    if not code or len(code) != 2 or not code.isalpha():
        return None
    return flag(code) if emoji else code.upper()


def aligulac_rating(rating: float | None, position: int | None) -> str | None:
    """Aligulac's site shows the API rating as ``(r + 1) * 1000`` (its ``ratscale``).

    New players start at 0 internally (1,000 on the site); weak players go negative.
    """
    if rating is None:
        return None
    shown = round((rating + 1.0) * 1000)
    if shown <= 0:
        return None
    return f"Aligulac {shown:,}" + (f" (#{position})" if position else "")


def earnings(amount: int | None) -> str | None:
    return f"${amount:,} earnings" if amount else None


def link_label(link_type: str) -> str:
    """``REPLAY_STATS`` -> ``Replay Stats``."""
    special = {"BATTLE_NET": "Battle.net", "YOUTUBE": "YouTube", "BILIBILI": "Bilibili"}
    return special.get(link_type, link_type.replace("_", " ").title())


def climb(slope_per_day: float | None) -> str | None:
    if slope_per_day is None or abs(slope_per_day) < 1:
        return None
    return f"{slope_per_day:+.0f}/day"
