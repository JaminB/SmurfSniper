from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from pydantic import BaseModel, ConfigDict
from PySide6.QtCore import QTimer

from smurfsniper.models.player_log import PlayerLog
from smurfsniper.ui.overlays import Overlay


class PlayerLogAnalysis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    logs: List[PlayerLog]

    @classmethod
    def from_battlenet_id(cls, battlenet_id: int, limit: int = 40):
        rows = list(
            PlayerLog.select()
            .where(PlayerLog.battlenet_id == battlenet_id)
            .order_by(PlayerLog.created_at.desc())
            .limit(limit)
        )
        if not rows:
            raise ValueError("No PlayerLog entries found")
        return cls(logs=rows)

    @property
    def name(self) -> str:
        return self.logs[0].name

    @property
    def region(self) -> str:
        return self.logs[0].region

    @property
    def first_encounter(self) -> Tuple[datetime, str]:
        last = self.logs[-1]
        return last.created_at, last.match_status

    @property
    def last_encounter(self) -> Tuple[datetime, str]:
        first = self.logs[0]
        return first.created_at, first.match_status

    @staticmethod
    def _map_to_me(status: str) -> str:
        return {
            "victory": "loss",
            "defeat": "win",
            "tie": "tie",
        }[status]

    @property
    def times_played(self) -> int:
        return len(self.logs)

    @property
    def record_vs_me(self) -> Tuple[int, int, int]:
        wins = losses = ties = 0
        for log in self.logs:
            outcome = self._map_to_me(log.match_status)
            if outcome == "win":
                wins += 1
            elif outcome == "loss":
                losses += 1
            else:
                ties += 1
        return wins, losses, ties

    def summary(self) -> dict:
        wins, losses, ties = self.record_vs_me
        return {
            "player": self.name,
            "region": self.region,
            "times_played": self.times_played,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "first_played_at": self.first_encounter[0],
            "last_played_at": self.last_encounter[0],
        }

    def _top_block(self) -> str:
        return "\n".join(
            [
                f"{self.name} ({self.region})",
                f"Played {self.times_played} times",
            ]
        )

    def _record_block(self) -> str:
        wins, losses, ties = self.record_vs_me
        record = f"{wins}W – {losses}L"
        if ties:
            record += f" – {ties}T"
        return f"Your record: {record}"

    def _dates_block(self) -> str:
        first = self.first_encounter[0].strftime("%Y-%m-%d")
        last = self.last_encounter[0].strftime("%Y-%m-%d")
        return f"First: {first}   Last: {last}"

    def show_overlay(
        self,
        duration_seconds: int = 25,
        position: str = "top_left",
        orientation: str = "vertical",
        delay_seconds: float = 0.0,
    ):
        ov = Overlay(
            duration_seconds=duration_seconds,
            position=position,
        )

        blocks = [
            self._top_block(),
            self._record_block(),
            self._dates_block(),
        ]

        if orientation == "vertical":
            for b in blocks:
                ov.add_row([b], style=Overlay.PLAYER_STYLE, spacing=12)
        else:
            ov.add_row(blocks, style=Overlay.PLAYER_STYLE, spacing=12)

        if delay_seconds <= 0:
            ov.show()
            return

        def delayed_show():
            ov.show()

        delay_ms = int(delay_seconds * 1000)
        QTimer.singleShot(delay_ms, delayed_show)
