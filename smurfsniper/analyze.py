from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

from smurfsniper.enums import League, RaceCode
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


class PlayerAnalysis(BaseModel):
    current_race: Optional[str] = None
    player_stats: PlayerStats

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
        best_match = player.get_best_match()
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
    def first_game_played(self) -> Optional[datetime]:
        return self.player_stats.match_history.first_game_played

    @property
    def last_game_played(self) -> Optional[datetime]:
        return self.player_stats.match_history.last_game_played

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
    def mmr_trend(self) -> str:
        hist = self.player_stats.match_history
        if not hist or len(hist.ratings) < 5:
            return "unknown"

        y = hist.ratings[-100:]
        n = len(y)
        x = list(range(n))

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        den = sum((xi - mean_x) ** 2 for xi in x)
        if den == 0:
            return "unknown"

        slope = num / den

        if slope > 1.5:
            return "strong rising"
        if slope > 0.4:
            return "rising"
        if slope < -1.5:
            return "strong falling"
        if slope < -0.4:
            return "falling"
        return "flat"

    @property
    def total_games(self) -> int:
        return self.player_stats.totalGamesPlayed

    @property
    def most_played_race(self) -> str:
        races = self.player_stats.members.raceGames
        if not races:
            return "unknown"
        key = max(races, key=lambda r: races.get(r, 0))
        return RaceCode[key].name

    @property
    def smurf_warning(self) -> Optional[str]:
        h = self.player_stats.match_history
        if not h:
            return None

        w3, l3 = h.wins_last_3_days, h.losses_last_3_days
        if (w3 + l3) >= 5:
            winrate3 = w3 / (w3 + l3)
            if winrate3 >= 0.80:
                return "⚠️ Likely Smurf (3d winrate ≥ 80%)"

        w7, l7 = h.wins_last_week, h.losses_last_week
        if (w7 + l7) >= 8:
            winrate7 = w7 / (w7 + l7)
            if winrate7 >= 0.75:
                return "⚠️ Possible Smurf (7d winrate ≥ 75%)"

        wl, ll = h.wins_lifetime, h.losses_lifetime
        if (wl + ll) >= 30:
            winrate_lf = wl / (wl + ll)
            if winrate_lf >= 0.70:
                return "⚠️ Suspiciously strong lifetime winrate"

        return None

    @property
    def wins_last_day(self) -> int:
        return self.player_stats.match_history.wins_last_day

    @property
    def losses_last_day(self) -> int:
        return self.player_stats.match_history.losses_last_day

    @property
    def wins_last_3_days(self) -> int:
        return self.player_stats.match_history.wins_last_3_days

    @property
    def losses_last_3_days(self) -> int:
        return self.player_stats.match_history.losses_last_3_days

    @property
    def wins_last_week(self) -> int:
        return self.player_stats.match_history.wins_last_week

    @property
    def losses_last_week(self) -> int:
        return self.player_stats.match_history.losses_last_week

    @property
    def wins_last_month(self) -> int:
        return self.player_stats.match_history.wins_last_month

    @property
    def losses_last_month(self) -> int:
        return self.player_stats.match_history.losses_last_month

    @property
    def wins_lifetime(self) -> int:
        return self.player_stats.match_history.wins_lifetime

    @property
    def losses_lifetime(self) -> int:
        return self.player_stats.match_history.losses_lifetime

    @property
    def teammates(self) -> dict[str, dict[str, Optional[datetime]]]:
        result: dict[str, dict[str, Optional[datetime]]] = {}
        my_name = self.name
        history = self.player_stats.match_history

        if not history:
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
        partners_readable = {
            name: {
                "last_played": (
                    info["last_played"].isoformat()
                    if isinstance(info.get("last_played"), datetime)
                    else "unknown"
                ),
                "games": info.get("count", 0),
            }
            for name, info in self.teammates.items()
        }

        first = self.first_game_played
        return {
            "Player": self.name,
            "Playing For": (
                f"{human_friendly_duration(first)} ({first})" if first else "unknown"
            ),
            "Most Recent Game": self.last_game_played,
            "Max League": self.max_league,
            "Current MMR": self.current_mmr,
            "Trend": self.mmr_trend,
            "Smurf Warning": self.smurf_warning,
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

    def show_overlay(self, duration_seconds: int = 30):
        summary = self.summary()
        trend = _trend_symbol(self.mmr_trend)
        spark = _sparkline_for(self, days=7)

        current = summary["Current Race"]
        primary = summary["Most Played Race"]
        race_note = f" (→ {primary})" if current != primary else ""

        smurf = f"⚠ {self.smurf_warning}" if self.smurf_warning else ""

        top_block = "\n".join(
            [
                f"{summary['Player']} | {summary['Max League']}",
                f"MMR {summary['Current MMR']} {trend}    {spark}",
                f"Race: {current}{race_note}",
                f"First Played: {summary['Playing For']}",
                smurf,
            ]
        )

        perf_block = (
            f"1d {summary['Wins (1d)']}W/{summary['Losses (1d)']}L   "
            f"3d {summary['Wins (3d)']}W/{summary['Losses (3d)']}L\n"
            f"7d {summary['Wins (7d)']}W/{summary['Losses (7d)']}L   "
            f"30d {summary['Wins (30d)']}W/{summary['Losses (30d)']}L\n"
            f"LFT {summary['Lifetime Wins']}W/{summary['Lifetime Losses']}L"
        )

        teammates = "\n".join(_top_teammate_rows(self, limit=3, include_games=False))

        ov = Overlay(duration_seconds)

        ov.add_row(
            [top_block, perf_block, teammates],
            style=Overlay.PLAYER_STYLE,
            spacing=12,
        )

        ov.show()


class Team2V2Analysis:
    def __init__(self, p1: PlayerAnalysis, p2: PlayerAnalysis):
        self.p1 = p1
        self.p2 = p2

    def summary(self) -> dict:
        s1 = self.p1.summary()
        s2 = self.p2.summary()

        def safe_avg(a, b):
            if a is None or b is None:
                return None
            return round((a + b) / 2, 1)

        combined_perf = {
            "Wins (1d)": s1["Wins (1d)"] + s2["Wins (1d)"],
            "Losses (1d)": s1["Losses (1d)"] + s2["Losses (1d)"],
            "Wins (3d)": s1["Wins (3d)"] + s2["Wins (3d)"],
            "Losses (3d)": s1["Losses (3d)"] + s2["Losses (3d)"],
            "Wins (7d)": s1["Wins (7d)"] + s2["Wins (7d)"],
            "Losses (7d)": s1["Losses (7d)"] + s2["Losses (7d)"],
            "Wins (30d)": s1["Wins (30d)"] + s2["Wins (30d)"],
            "Losses (30d)": s1["Losses (30d)"] + s2["Losses (30d)"],
            "Wins (Lifetime)": s1["Lifetime Wins"] + s2["Lifetime Wins"],
            "Losses (Lifetime)": s1["Lifetime Losses"] + s2["Lifetime Losses"],
        }

        most_recent = max(
            s1["Most Recent Game"],
            s2["Most Recent Game"],
        )

        return {
            "Team Players": [s1["Player"], s2["Player"]],
            "Avg MMR": safe_avg(s1["Current MMR"], s2["Current MMR"]),
            "MMR Trends": {
                s1["Player"]: s1["Trend"],
                s2["Player"]: s2["Trend"],
            },
            "Smurf Warnings": {
                s1["Player"]: s1["Smurf Warning"],
                s2["Player"]: s2["Smurf Warning"],
            },
            "Races": {
                s1["Player"]: {
                    "Current": s1["Current Race"],
                    "Primary": s1["Most Played Race"],
                },
                s2["Player"]: {
                    "Current": s2["Current Race"],
                    "Primary": s2["Most Played Race"],
                },
            },
            "Performance (Combined)": combined_perf,
            "Most Recent Match Time": most_recent,
            "Frequent Teammates": {
                s1["Player"]: s1["Frequent Teammates"],
                s2["Player"]: s2["Frequent Teammates"],
            },
        }

    def _build_player_block_for_print(self, p: PlayerAnalysis) -> str:
        s = p.summary()
        trend_symbol = _trend_symbol(p.mmr_trend)

        race_note = ""
        if s["Current Race"] != s["Most Played Race"]:
            race_note = f" (→ {s['Most Played Race']})"

        smurf_note = p.smurf_warning or ""

        lines = [
            f"{s['Player']}",
            f"MMR: {s['Current MMR']}  {trend_symbol}",
            f"Race: {s['Current Race']}{race_note}",
        ]
        if smurf_note:
            lines.append(f"⚠ {smurf_note}")

        lines.extend(
            [
                "",
                "Perf:",
                f"1d  {s['Wins (1d)']}W/{s['Losses (1d)']}L",
                f"3d  {s['Wins (3d)']}W/{s['Losses (3d)']}L",
                f"7d  {s['Wins (7d)']}W/{s['Losses (7d)']}L",
                f"30d {s['Wins (30d)']}W/{s['Losses (30d)']}L",
                f"LFT {s['Lifetime Wins']}W/{s['Lifetime Losses']}L",
            ]
        )
        return "\n".join(lines)

    def _build_teammate_table_for_print(self, p: PlayerAnalysis) -> str:
        rows = []
        for name, info in p.teammates.items():
            ts = info.get("last_played")
            ts_str = ts.isoformat() if isinstance(ts, datetime) else "unknown"
            games = info.get("count", 0)
            rows.append(f"{name:<14}  {ts_str:<22}  {games:>2}g")
        return "\n".join(rows) if rows else "(no teammate history)"

    def show_overlay(self, duration_seconds: int = 40):
        """
        Ultra-compact 2v2 HUD.
        """

        def build_compact_block(p: PlayerAnalysis) -> str:
            s = p.summary()
            trend = _trend_symbol(p.mmr_trend)
            spark = _sparkline_for(p, days=7)

            race_note = ""
            if s["Current Race"] != s["Most Played Race"]:
                race_note = f"(→ {s['Most Played Race']})"

            smurf = f"⚠ {p.smurf_warning}" if p.smurf_warning else ""
            league = s.get("Max League", "")
            first_played = s.get("Playing For", "")

            perf = (
                f"1d {s['Wins (1d)']}W/{s['Losses (1d)']}L   "
                f"3d {s['Wins (3d)']}W/{s['Losses (3d)']}L   "
                f"7d {s['Wins (7d)']}W/{s['Losses (7d)']}L   "
                f"30d {s['Wins (30d)']}W/{s['Losses (30d)']}L   "
                f"LFT {s['Lifetime Wins']}W/{s['Lifetime Losses']}L"
            )

            return "\n".join(
                [
                    f"{s['Player']}   {league}",
                    f"MMR {s['Current MMR']} {trend}   {spark}",
                    f"Race {s['Current Race']}{race_note} {smurf}",
                    first_played,
                    perf,
                ]
            )

        def build_teammates(p: PlayerAnalysis) -> str:
            return "\n".join(_top_teammate_rows(p, limit=3, include_games=True))

        ov = Overlay(duration_seconds)

        # Player row
        ov.add_row(
            [
                build_compact_block(self.p1),
                build_compact_block(self.p2),
            ],
            style=Overlay.PLAYER_STYLE,
        )

        # Teammates row
        ov.add_row(
            [
                build_teammates(self.p1),
                build_teammates(self.p2),
            ],
            style=Overlay.TM_STYLE,
        )

        ov.show()
