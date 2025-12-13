from PySide6.QtCore import QTimer

from smurfsniper.ui.overlays import Overlay

TREND_SYMBOLS: dict[str, str] = {
    "strong rising": "▲▲",
    "rising": "▲",
    "falling": "▼",
    "strong falling": "▼▼",
    "flat": "→",
    "unknown": "?",
}

POSITION_MAP = {
    "center": "center",
    "top_left": "top_left",
    "top_right": "top_right",
    "bottom_left": "bottom_left",
    "bottom_right": "bottom_right",
}



class BaseAnalysis:
    @property
    def match_history(self):
        raise NotImplementedError

    def summary(self) -> dict:
        raise NotImplementedError

    def _overlay_top_details(self, summary: dict) -> list[str]:
        raise NotImplementedError

    def _overlay_side_panel(self, summary: dict) -> str:
        return ""

    def trend_symbol(self) -> str:
        return TREND_SYMBOLS.get(self.mmr_trend, "?")

    def sparkline(self, days: int = 7) -> str:
        mh = self.match_history
        if not mh:
            return ""
        return mh.sparkline(days=days)

    @property
    def first_game_played(self):
        mh = self.match_history
        return mh.first_game_played if mh else None

    @property
    def last_game_played(self):
        mh = self.match_history
        return mh.last_game_played if mh else None

    @property
    def mmr_trend(self) -> str:
        mh = self.match_history
        if not mh or len(mh.ratings) < 5:
            return "unknown"

        y = mh.ratings[-100:]
        n = len(y)
        x = range(n)
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
    def wins_last_day(self):
        return self.match_history.wins_last_day

    @property
    def losses_last_day(self):
        return self.match_history.losses_last_day

    @property
    def wins_last_3_days(self):
        return self.match_history.wins_last_3_days

    @property
    def losses_last_3_days(self):
        return self.match_history.losses_last_3_days

    @property
    def wins_last_week(self):
        return self.match_history.wins_last_week

    @property
    def losses_last_week(self):
        return self.match_history.losses_last_week

    @property
    def wins_last_month(self):
        return self.match_history.wins_last_month

    @property
    def losses_last_month(self):
        return self.match_history.losses_last_month

    @property
    def wins_lifetime(self):
        return self.match_history.wins_lifetime

    @property
    def losses_lifetime(self):
        return self.match_history.losses_lifetime

    def _resolve_overlay_layout(self, orientation: str):
        """Returns layout blocks based on user-configured orientation."""
        summary = self.summary()

        top_block = "\n".join(self._overlay_top_details(summary))
        perf_block = (
            f"1d {summary['Wins (1d)']}W/{summary['Losses (1d)']}L   "
            f"3d {summary['Wins (3d)']}W/{summary['Losses (3d)']}L\n"
            f"7d {summary['Wins (7d)']}W/{summary['Losses (7d)']}L   "
            f"30d {summary['Wins (30d)']}W/{summary['Losses (30d)']}L\n"
            f"LFT {summary['Lifetime Wins']}W/{summary['Lifetime Losses']}L"
        )
        side_block = self._overlay_side_panel(summary)

        if orientation == "vertical":
            # stacked layout
            return [[top_block], [perf_block], [side_block]]

        # default horizontal
        return [[top_block, perf_block, side_block]]

    def show_overlay(
            self,
            duration_seconds: int = 30,
            position: str = "top_center",
            orientation: str = "vertical",
            delay_seconds: float = 0.0,
    ):
        rows = self._resolve_overlay_layout(orientation)

        ov = Overlay(duration_seconds)
        ov.position = position

        for row in rows:
            ov.add_row(row, style=Overlay.PLAYER_STYLE, spacing=12)

        if delay_seconds <= 0:
            ov.show()
            return

        def delayed_show():
            ov.show()

        delay_ms = int(delay_seconds * 1000)
        QTimer.singleShot(delay_ms, delayed_show)



