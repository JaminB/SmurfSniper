"""On-demand scouting intel for the current opponent(s) (Ctrl+F2).

Two layers, both rendered into one overlay:

* **Behavioral profile** — derived purely from the opponent's own ranked match
  history (already fetched from SC2Pulse): recent form, current streak, active
  hours, favourite maps, average game length. No web calls, no PII.
* **Cross-network footprint** — only when the in-game handle is distinctive
  enough to be worth a public web lookup (Aligulac / Liquipedia / Twitch-live /
  candidate handle URLs).

Network fetches run off the Qt thread (in the hotkey thread); only
``render_overlay`` touches Qt widgets.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer

from smurfsniper.api import cross_network
from smurfsniper.logger import logger
from smurfsniper.models.config import OverlayPreferences
from smurfsniper.models.match import (
    RecentMatch,
    avg_duration_seconds,
    ladder_only,
    map_records,
)
from smurfsniper.models.player import PlayerStats
from smurfsniper.ui.overlays import Overlay

_BARS = "▁▂▃▄▅▆▇█"


def _activity_sparkline(hour_counts: Counter) -> str:
    """24-char bar of games-per-hour-of-day (00h → 23h)."""
    peak = max(hour_counts.values()) if hour_counts else 0
    if not peak:
        return ""
    out = []
    for h in range(24):
        c = hour_counts.get(h, 0)
        out.append(" " if c == 0 else _BARS[min(len(_BARS) - 1, (c * (len(_BARS) - 1)) // peak)])
    return "".join(out)


def _peak_window(hour_counts: Counter) -> Optional[str]:
    """Most-active 3-hour window, e.g. '19–22h'."""
    if not hour_counts:
        return None
    best_start, best_sum = 0, -1
    for start in range(24):
        total = sum(hour_counts.get((start + i) % 24, 0) for i in range(3))
        if total > best_sum:
            best_start, best_sum = start, total
    if best_sum <= 0:
        return None
    return f"{best_start:02d}–{(best_start + 3) % 24:02d}h"


def _fmt_seconds(secs: Optional[int]) -> Optional[str]:
    if not secs:
        return None
    m, s = divmod(int(secs), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _current_streak(matches: List[RecentMatch]) -> str:
    """Streak from most-recent match backwards, e.g. 'W3' / 'L2'."""
    if not matches:
        return ""
    # matches come newest-first from SC2Pulse; guard by sorting on date desc.
    ordered = sorted(matches, key=lambda m: m.date, reverse=True)
    first = ordered[0].decision
    if first not in ("WIN", "LOSS"):
        return ""
    n = 0
    for m in ordered:
        if m.decision != first:
            break
        n += 1
    return f"{'W' if first == 'WIN' else 'L'}{n}"


@dataclass
class BehaviorProfile:
    games: int
    wins: int
    losses: int
    streak: str
    peak_window: Optional[str]
    activity: str
    top_maps: List[Tuple[str, int, int]]  # (map, wins, losses)
    avg_duration: Optional[str]

    @classmethod
    def from_stats(cls, stats: PlayerStats) -> Optional["BehaviorProfile"]:
        matches = ladder_only(stats.recent_matches())
        if not matches:
            return None

        wins = sum(1 for m in matches if m.decision == "WIN")
        losses = sum(1 for m in matches if m.decision == "LOSS")
        hour_counts = Counter(m.date.hour for m in matches)

        records = map_records(matches)
        top_maps = sorted(
            ((name, w, l) for name, (w, l) in records.items()),
            key=lambda r: r[1] + r[2],
            reverse=True,
        )[:3]

        return cls(
            games=len(matches),
            wins=wins,
            losses=losses,
            streak=_current_streak(matches),
            peak_window=_peak_window(hour_counts),
            activity=_activity_sparkline(hour_counts),
            top_maps=top_maps,
            avg_duration=_fmt_seconds(avg_duration_seconds(matches)),
        )

    def to_lines(self) -> List[str]:
        lines: List[str] = []
        form = f"Form: {self.wins}W/{self.losses}L (last {self.games})"
        if self.streak:
            form += f"  streak {self.streak}"
        lines.append(form)

        if self.peak_window or self.activity:
            act = "Active: "
            if self.peak_window:
                act += f"peak {self.peak_window}  "
            if self.activity:
                act += self.activity
            lines.append(act.rstrip())

        if self.top_maps:
            maps = "  ".join(f"{name} {w}-{l}" for name, w, l in self.top_maps)
            lines.append(f"Maps: {maps}")

        if self.avg_duration:
            lines.append(f"Avg game: {self.avg_duration}")

        return lines


@dataclass
class ExternalIntel:
    name: str
    region: str
    behavior: Optional[BehaviorProfile] = None
    aligulac: Optional[dict] = None
    liquipedia: Optional[Tuple[str, str]] = None
    twitch_live: Optional[dict] = None
    handle_urls: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def gather(cls, stats: PlayerStats) -> "ExternalIntel":
        """Build the scouting profile. Network calls run here, off the Qt thread.

        The behavioral profile is always computed (own match data). External web
        sources (Aligulac / Liquipedia / handle URLs) are gathered only when the
        handle is distinctive enough; Twitch-live matches by character id so it
        always runs.
        """
        char = stats.members.character
        name = char.name

        behavior = BehaviorProfile.from_stats(stats)
        twitch = cross_network.twitch_live(char.id)

        aligulac = liquipedia = None
        handle_urls: Dict[str, str] = {}
        if cross_network.is_distinctive_name(name):
            logger.info(f"Ctrl+F2: gathering cross-network intel for {name!r}.")
            aligulac = cross_network.aligulac_player(name)
            liquipedia = cross_network.liquipedia_page(name)
            handle_urls = cross_network.candidate_handle_urls(name)
        else:
            logger.info(f"Ctrl+F2: {name!r} not distinctive — web lookup skipped.")

        return cls(
            name=name,
            region=char.region,
            behavior=behavior,
            aligulac=aligulac,
            liquipedia=liquipedia,
            twitch_live=twitch,
            handle_urls=handle_urls,
        )

    def to_block(self) -> str:
        """Render this opponent's intel as a single overlay text block."""
        base = self.name.split("#")[0].strip()
        lines = [f"🔎 {base}  ({self.region})"]

        if self.behavior:
            lines.extend(self.behavior.to_lines())

        if self.aligulac:
            bio = " · ".join(
                p for p in (
                    self.aligulac.get("country"),
                    self.aligulac.get("name"),
                    self.aligulac.get("race"),
                ) if p
            )
            url = self.aligulac.get("profile_url")
            lines.append(f"Aligulac: {bio or '?'}" + (f"\n  {url}" if url else ""))

        if self.liquipedia:
            title, url = self.liquipedia
            lines.append(f"Liquipedia: {title}\n  {url}")

        if self.twitch_live:
            title = self.twitch_live.get("title") or "live now"
            url = self.twitch_live.get("url")
            lines.append(f"🔴 Twitch LIVE: {title}" + (f"\n  {url}" if url else ""))

        if self.handle_urls:
            guesses = "  ".join(self.handle_urls.values())
            lines.append(f"guesses: {guesses}")

        if len(lines) == 1:
            lines.append("no scouting data found")

        return "\n".join(lines)


def render_overlay(
    intels: List[ExternalIntel], prefs: OverlayPreferences
) -> None:
    """Build and show the scouting overlay. Must run on the Qt thread."""
    if not intels:
        return

    ov = Overlay(prefs.seconds_visible)
    ov.position = prefs.position

    for intel in intels:
        ov.add_row([intel.to_block()], style=Overlay.PLAYER_STYLE, spacing=12)

    delay = prefs.seconds_delay_before_show
    if delay <= 0:
        ov.show()
        return
    QTimer.singleShot(int(delay * 1000), ov.show)
