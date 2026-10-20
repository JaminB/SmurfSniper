"""What an opponent tends to do, from their recent ladder matches (pure functions)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import tzinfo

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.matches import RecentResult, recent_results
from smurfsniper.api.sc2pulse.models import LadderMatch

MIN_MATCHES = 3
MIN_HOURS_GAMES = 10
MIN_SHORT_WINS = 5
SHORT_WIN_SECONDS = 360
FORM_LENGTH = 10
MAP_LIMIT = 5
WINDOW_HOURS = 3


@dataclass(frozen=True)
class Tendencies:
    games: int
    vs_race: dict[str, Record]  # their record against each race (ZERG/TERRAN/PROTOSS/RANDOM)
    maps: dict[str, Record]  # top 5 by games
    avg_duration_s: int | None
    short_win_rate: float | None  # share of wins under 6 min; None if fewer than 5 wins
    form: tuple[str, ...]  # last 10 decisions, newest first, "W" / "L"
    streak: tuple[str, int] | None
    active_hours: tuple[int, ...] | None  # 24 counts in local time; None if games < 10
    peak_hours: tuple[int, int] | None  # (start, end) of the busiest 3 h window
    race_switches: int  # matches where their race was not their most played one
    races_played: dict[str, int]


def _records(pairs: Sequence[tuple[str, bool]]) -> dict[str, Record]:
    acc: dict[str, list[int]] = {}
    for key, won in pairs:
        wl = acc.setdefault(key, [0, 0])
        wl[0 if won else 1] += 1
    return {k: Record(w, lo) for k, (w, lo) in acc.items()}


def peak_window(hours: Sequence[int], width: int = WINDOW_HOURS) -> tuple[int, int] | None:
    """Busiest contiguous ``width``-hour window as (start, end) hour, wrapping midnight."""
    if not any(hours):
        return None
    best_start, best = 0, -1
    for start in range(24):
        total = sum(hours[(start + i) % 24] for i in range(width))
        if total > best:
            best_start, best = start, total
    return best_start, (best_start + width) % 24


def _streak(form: Sequence[str]) -> tuple[str, int] | None:
    if not form:
        return None
    n = 0
    for f in form:
        if f != form[0]:
            break
        n += 1
    return form[0], n


def tendencies(
    matches: Sequence[LadderMatch], character_id: int, *, tz: tzinfo
) -> Tendencies | None:
    """None when fewer than 3 decided ladder matches are known."""
    results: list[RecentResult] = recent_results(matches, character_id)  # newest first
    if len(results) < MIN_MATCHES:
        return None

    vs = _records([(r.opponent_race, r.won) for r in results if r.opponent_race])
    maps_all = _records([(r.map, r.won) for r in results if r.map])
    maps = dict(sorted(maps_all.items(), key=lambda kv: -kv[1].games)[:MAP_LIMIT])

    durations = [r.duration_s for r in results if r.duration_s]
    avg = round(sum(durations) / len(durations)) if durations else None

    win_durations = [r.duration_s for r in results if r.won and r.duration_s]
    short = None
    if len(win_durations) >= MIN_SHORT_WINS:
        short = sum(1 for d in win_durations if d < SHORT_WIN_SECONDS) / len(win_durations)

    form = tuple("W" if r.won else "L" for r in results[:FORM_LENGTH])

    hours = None
    peak = None
    if len(results) >= MIN_HOURS_GAMES:
        counts = [0] * 24
        for r in results:
            counts[r.ts.astimezone(tz).hour] += 1
        hours = tuple(counts)
        peak = peak_window(hours)

    played = Counter(r.race for r in results if r.race)
    switches = 0
    if played:
        main = played.most_common(1)[0][0]
        switches = sum(n for race, n in played.items() if race != main)

    return Tendencies(
        games=len(results),
        vs_race=vs,
        maps=maps,
        avg_duration_s=avg,
        short_win_rate=short,
        form=form,
        streak=_streak(form),
        active_hours=hours,
        peak_hours=peak,
        race_switches=switches,
        races_played=dict(played),
    )
