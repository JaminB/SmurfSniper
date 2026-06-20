from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel
from PySide6.QtCore import QTimer

from smurfsniper.analyze import BaseAnalysis
from smurfsniper.enums import League, RaceCode
from smurfsniper.models.match import (
    RecentMatch,
    avg_duration_seconds,
    ladder_only,
    map_records,
)
from smurfsniper.models.player import Player, PlayerStats
from smurfsniper.ui.overlays import Overlay
from smurfsniper.utils import human_friendly_duration

_TREND_SYMBOLS: Dict[str, str] = {
    "strong rising": "▲▲",
    "rising": "▲",
    "falling": "▼",
    "strong falling": "▼▼",
    "flat": "→",
    "unknown": "?",
}


def _trend_symbol(trend: str) -> str:
    return _TREND_SYMBOLS.get(trend, "?")


def _sparkline_for(player_analysis: "PlayerAnalysis", days: int = 7) -> str:
    hist = player_analysis.player_stats.match_history
    if not hist:
        return ""
    return hist.sparkline(days=days)


def _top_teammate_rows(
    p: "PlayerAnalysis",
    limit: int = 3,
    include_games: bool = False,
) -> List[str]:
    rows: List[str] = []
    for idx, (name, info) in enumerate(p.teammates.items()):
        if idx >= limit:
            break
        ts = info.get("last_played")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else "unknown"
        if include_games:
            games = info.get("count", 0)
            rows.append(f"{name:<12} {games:>2}g  {ts_str}")
        else:
            rows.append(f"{name:<14} {ts_str}")
    return rows or ["(none)"]


class PlayerAnalysis(BaseAnalysis, BaseModel):
    current_race: Optional[str] = None
    player_stats: PlayerStats

    @property
    def match_history(self):
        return self.player_stats.match_history

    @classmethod
    def from_player_name(cls, str_player_name: str) -> "PlayerAnalysis":
        str_player_name = str_player_name.strip()
        return cls.from_player(
            Player(
                id=1,
                name=str_player_name,
                type="user",
                result="Undecided",
                race="Unknown",
            )
        )

    @classmethod
    def from_player(cls, player: Player) -> "PlayerAnalysis":
        best_match = player.get_player_stats()
        stats = PlayerStats.model_validate(best_match)
        return cls(player_stats=stats)

    @classmethod
    def from_player_stats(
        cls, player_stats: PlayerStats, player: Optional[Player] = None
    ) -> "PlayerAnalysis":
        current_race = "Unknown"
        if player and player.race is not None:
            current_race = RaceCode.from_alias(player.race).name
        return cls(player_stats=player_stats, current_race=current_race)

    @property
    def name(self) -> str:
        return self.player_stats.members.character.name

    @property
    def max_league(self) -> str:
        return League.from_int(self.player_stats.leagueMax).name

    @property
    def current_mmr(self) -> Optional[int]:
        return (
            self.player_stats.currentStats.rating
            or self.player_stats.previousStats.rating
        )

    @property
    def previous_mmr(self) -> Optional[int]:
        return self.player_stats.previousStats.rating

    @property
    def total_games(self) -> int:
        return self.player_stats.totalGamesPlayed

    @property
    def pro_identity(self) -> Optional[str]:
        """Revealed pro/streamer name + team, e.g. '👑 Serral [BSLSK]'."""
        m = self.player_stats.members
        if not m.proNickname:
            return None
        team = f" [{m.proTeam}]" if m.proTeam else ""
        return f"👑 {m.proNickname}{team}"

    @property
    def pro_twitch(self) -> Optional[str]:
        """Twitch URL for a revealed pro (lazy fetch; pros only)."""
        if not self.player_stats.is_pro:
            return None
        return self.player_stats.social_links().get("TWITCH")

    @property
    def recent_matches(self) -> List[RecentMatch]:
        """Recent ranked-ladder matches (CUSTOM / co-op excluded)."""
        return ladder_only(self.player_stats.recent_matches())

    @property
    def map_records(self) -> Dict[str, tuple[int, int]]:
        return map_records(self.recent_matches)

    @property
    def avg_game_duration(self) -> Optional[int]:
        return avg_duration_seconds(self.recent_matches)

    @property
    def real_record(self) -> Optional[str]:
        """Win/loss from real match history (more exact than MMR-delta inference).

        Returns None when SC2Pulse has no tracked matches for this player.
        """
        matches = self.recent_matches
        if not matches:
            return None
        wins = sum(1 for m in matches if m.decision == "WIN")
        losses = sum(1 for m in matches if m.decision == "LOSS")
        return f"{wins}W/{losses}L (last {len(matches)})"

    @property
    def map_summary(self) -> Optional[str]:
        """Compact per-map record string, e.g. 'Goldenaura 3-1 · Site 2-0'."""
        records = self.map_records
        if not records:
            return None
        ordered = sorted(records.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
        return " · ".join(f"{name} {w}-{l}" for name, (w, l) in ordered[:3])

    @property
    def most_played_race(self) -> str:
        races = self.player_stats.members.raceGames
        if not races:
            return "unknown"
        key = max(races, key=lambda r: races.get(r, 0))
        return RaceCode[key].name

    def _smurf_assessment(self) -> tuple[int, List[str]]:
        """Graded smurf likelihood (0–100) with human-readable reasons.

        Blends recent/lifetime winrate with account age and MMR climb velocity.
        Each signal contributes weighted points; the total is capped at 100.
        """
        h = self.match_history
        if not h:
            return 0, []

        score = 0
        reasons: List[str] = []

        w3, l3 = h.wins_last_3_days, h.losses_last_3_days
        if (w3 + l3) >= 5 and (w3 / (w3 + l3)) >= 0.80:
            score += 35
            reasons.append(f"3d winrate {w3}/{w3 + l3} ≥80%")

        w7, l7 = h.wins_last_week, h.losses_last_week
        if (w7 + l7) >= 8 and (w7 / (w7 + l7)) >= 0.75:
            score += 25
            reasons.append(f"7d winrate {w7}/{w7 + l7} ≥75%")

        wl, ll = h.wins_lifetime, h.losses_lifetime
        if (wl + ll) >= 30 and (wl / (wl + ll)) >= 0.70:
            score += 15
            reasons.append("lifetime winrate ≥70%")

        # Account-age and climb signals need enough history to be meaningful.
        if len(h.ratings) >= 5:
            age = h.account_age_days
            if age <= 14:
                score += 30
                reasons.append(f"new account ({age}d)")
            elif age <= 30:
                score += 18
                reasons.append(f"young account ({age}d)")

            v = h.mmr_climb_velocity
            if v >= 15:
                score += 20
                reasons.append(f"fast MMR climb ({v:.0f}/day)")
            elif v >= 8:
                score += 10
                reasons.append(f"steady MMR climb ({v:.0f}/day)")

        return min(score, 100), reasons

    @property
    def smurf_score(self) -> int:
        return self._smurf_assessment()[0]

    @property
    def smurf_reasons(self) -> List[str]:
        return self._smurf_assessment()[1]

    @property
    def smurf_warning(self) -> Optional[str]:
        score, reasons = self._smurf_assessment()
        if score >= 70:
            label = "⚠️ Likely Smurf"
        elif score >= 45:
            label = "⚠️ Possible Smurf"
        elif score >= 25:
            label = "⚠️ Suspiciously strong"
        else:
            return None

        detail = f" – {reasons[0]}" if reasons else ""
        return f"{label} ({score}/100){detail}"

    @property
    def teammates(self) -> Dict[str, Dict[str, Optional[datetime]]]:
        result = {}
        my_name = self.name
        if not self.match_history:
            return {}

        for team in self.player_stats.members.character.teams:
            ts = (
                datetime.fromisoformat(team.lastPlayed.replace("Z", ""))
                if team.lastPlayed
                else None
            )
            if not ts:
                continue

            for member in team.members:
                n = member.character.name
                if n == my_name:
                    continue

                entry = result.setdefault(n, {"count": 0, "last_played": None})
                entry["count"] += 1
                if entry["last_played"] is None or ts > entry["last_played"]:
                    entry["last_played"] = ts

        return result

    def summary(self) -> dict:
        first = self.first_game_played

        partners_readable = {
            name: {
                "last_played": (
                    info["last_played"].isoformat()
                    if isinstance(info["last_played"], datetime)
                    else "unknown"
                ),
                "games": info["count"],
            }
            for name, info in self.teammates.items()
        }

        return {
            "Player": self.name,
            "Playing For": (
                f"{human_friendly_duration(first)} ({first})" if first else "unknown"
            ),
            "Most Recent Game": self.last_game_played,
            "Max League": self.max_league,
            "Current MMR": self.current_mmr,
            "Trend": self.mmr_trend,
            "Pro": self.pro_identity,
            "Smurf Warning": self.smurf_warning,
            "Smurf Score": self.smurf_score,
            "Smurf Reasons": self.smurf_reasons,
            "Account Age (days)": self.account_age_days,
            "MMR Climb (per day)": round(self.mmr_climb_velocity, 1),
            "Real Record": self.real_record,
            "Recent Maps": self.map_summary,
            "Avg Duration (s)": self.avg_game_duration,
            "Current Race": self.current_race,
            "Most Played Race": self.most_played_race,
            "Total Games": self.total_games,
            "Wins (1d)": self.wins_last_day,
            "Losses (1d)": self.losses_last_day,
            "Wins (3d)": self.wins_last_3_days,
            "Losses (3d)": self.losses_last_3_days,
            "Wins (7d)": self.wins_last_week,
            "Losses (7d)": self.losses_last_week,
            "Wins (30d)": self.wins_last_month,
            "Losses (30d)": self.losses_last_month,
            "Lifetime Wins": self.wins_lifetime,
            "Lifetime Losses": self.losses_lifetime,
            "Frequent Teammates": partners_readable,
        }

    def _overlay_top_details(self, summary: dict) -> list[str]:
        trend = self.trend_symbol()
        spark = self.sparkline()

        race_note = ""
        if summary["Current Race"] != summary["Most Played Race"]:
            race_note = f" (→ {summary['Most Played Race']})"

        smurf = f"{summary['Smurf Warning']}" if summary["Smurf Warning"] else ""

        rows = [
            f"{summary['Player']} | {summary['Max League']}",
            f"MMR {summary['Current MMR']} {trend}    {spark}",
            f"Race: {summary['Current Race']}{race_note}",
            f"First Played: {summary['Playing For']}",
            smurf,
        ]
        if summary.get("Pro"):
            rows.insert(1, summary["Pro"])
        if summary.get("Real Record"):
            line = f"Recent {summary['Real Record']}"
            if summary.get("Recent Maps"):
                line += f"   {summary['Recent Maps']}"
            rows.append(line)
        return rows

    def _overlay_side_panel(self, summary: dict) -> str:
        return "\n".join(_top_teammate_rows(self, limit=3, include_games=True))

    def overlay_block(self) -> str:
        """Compact HUD block showing league, MMR, race, smurf warning."""
        s = self.summary()
        trend = _trend_symbol(self.mmr_trend)
        spark = _sparkline_for(self, days=7)

        race_note = ""
        if s["Current Race"] != s["Most Played Race"]:
            race_note = f"(→ {s['Most Played Race']})"

        smurf = f"⚠ {self.smurf_warning}" if self.smurf_warning else ""
        league = s.get("Max League", "")
        first_played = s.get("Playing For", "")

        perf = (
            f"1d {s['Wins (1d)']}W/{s['Losses (1d)']}L   "
            f"3d {s['Wins (3d)']}W/{s['Losses (3d)']}L   "
            f"7d {s['Wins (7d)']}W/{s['Losses (7d)']}L   "
            f"30d {s['Wins (30d)']}W/{s['Losses (30d)']}L   "
            f"LFT {s['Lifetime Wins']}W/{s['Lifetime Losses']}L"
        )

        lines = [
            f"{s['Player']}   {league}",
            f"MMR {s['Current MMR']} {trend}   {spark}",
            f"Race {s['Current Race']}{race_note} {smurf}",
            first_played,
            perf,
        ]
        if s.get("Pro"):
            lines.insert(1, s["Pro"])
        if s.get("Real Record"):
            extra = f"Recent {s['Real Record']}"
            if s.get("Recent Maps"):
                extra += f"   {s['Recent Maps']}"
            lines.append(extra)
        return "\n".join(lines)

    def overlay_teammates_block(self) -> str:
        """Compact teammates block for overlays."""
        return "\n".join(_top_teammate_rows(self, limit=3, include_games=True))


class Player2v2Analysis:
    """
    A thin wrapper around two PlayerAnalysis objects.
    No duplicated logic. No special helpers.
    All stats come from the underlying PlayerAnalysis instances.
    """

    def __init__(self, p1: PlayerAnalysis, p2: PlayerAnalysis):
        self.p1 = p1
        self.p2 = p2

    def summary(self) -> dict:
        s1 = self.p1.summary()
        s2 = self.p2.summary()

        def add(a, b):
            return (a or 0) + (b or 0)

        combined = {
            "Wins (1d)": add(s1["Wins (1d)"], s2["Wins (1d)"]),
            "Losses (1d)": add(s1["Losses (1d)"], s2["Losses (1d)"]),
            "Wins (3d)": add(s1["Wins (3d)"], s2["Wins (3d)"]),
            "Losses (3d)": add(s1["Losses (3d)"], s2["Losses (3d)"]),
            "Wins (7d)": add(s1["Wins (7d)"], s2["Wins (7d)"]),
            "Losses (7d)": add(s1["Losses (7d)"], s2["Losses (7d)"]),
            "Wins (30d)": add(s1["Wins (30d)"], s2["Wins (30d)"]),
            "Losses (30d)": add(s1["Losses (30d)"], s2["Losses (30d)"]),
            "Wins (Lifetime)": add(s1["Lifetime Wins"], s2["Lifetime Wins"]),
            "Losses (Lifetime)": add(s1["Lifetime Losses"], s2["Lifetime Losses"]),
        }

        return {
            "Players": [s1["Player"], s2["Player"]],
            "Avg MMR": (
                None
                if not s1["Current MMR"] or not s2["Current MMR"]
                else round((s1["Current MMR"] + s2["Current MMR"]) / 2)
            ),
            "Trends": {s1["Player"]: s1["Trend"], s2["Player"]: s2["Trend"]},
            "Smurfs": {
                s1["Player"]: s1["Smurf Warning"],
                s2["Player"]: s2["Smurf Warning"],
            },
            "Races": {
                s1["Player"]: (s1["Current Race"], s1["Most Played Race"]),
                s2["Player"]: (s2["Current Race"], s2["Most Played Race"]),
            },
            "Combined Performance": combined,
            "Most Recent Match": max(s1["Most Recent Game"], s2["Most Recent Game"]),
            "Frequent Teammates": {
                s1["Player"]: s1["Frequent Teammates"],
                s2["Player"]: s2["Frequent Teammates"],
            },
        }

    def show_overlay(
        self,
        duration_seconds: int = 30,
        position: str = "top_center",
        orientation: str = "vertical",
        delay_seconds: float = 0.0,
    ):
        ov = Overlay(
            duration_seconds=duration_seconds,
            position=position,
        )

        p1_main = self.p1.overlay_block()
        p2_main = self.p2.overlay_block()
        p1_tm = self.p1.overlay_teammates_block()
        p2_tm = self.p2.overlay_teammates_block()

        if orientation == "horizontal":
            ov.add_row([p1_main, p2_main], style=Overlay.PLAYER_STYLE)
            ov.add_row([p1_tm, p2_tm], style=Overlay.TM_STYLE)
        else:
            ov.add_row([p1_main], style=Overlay.PLAYER_STYLE)
            ov.add_row([p2_main], style=Overlay.PLAYER_STYLE)
            ov.add_row([p1_tm], style=Overlay.TM_STYLE)
            ov.add_row([p2_tm], style=Overlay.TM_STYLE)

        # No delay → show now
        if delay_seconds <= 0:
            ov.show()
            return

        # Delay using Qt timer
        def delayed_show():
            ov.show()

        delay_ms = int(delay_seconds * 1000)
        QTimer.singleShot(delay_ms, delayed_show)
