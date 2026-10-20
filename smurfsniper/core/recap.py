"""Post-game recap toast.

Two pushes share one toast id so the second updates the first in place:

1. when the game ends: ``Victory vs Bob (Zerg)`` / ``14:32 · Session 5-2 · You 2-1 vs Bob``;
2. when SC2Pulse reports the new rating: the same toast prefixed with ``+24 MMR (4,234) · ``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject, Slot

from smurfsniper.core import matching
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameResult
from smurfsniper.core.profile import OpponentProfile
from smurfsniper.core.session import SessionTracker
from smurfsniper.core.toasts import ToastSpec
from smurfsniper.storage.rows import SessionGame
from smurfsniper.textutil import RACE_LABEL, duration, join

# SC2Pulse is polled at 20 s, 90 s and 300 s after a game; leave room for the last one.
MMR_WINDOW = timedelta(minutes=5, seconds=30)
H2H_MIN_GAMES = 2
RECAP_TOAST_MS = 10_000  # equals ui.tokens.ANIM['toast_recap_ms'] (tested)


def opponent_text(game: SessionGame) -> str:
    names = [o.name for o in game.opponents]
    if len(names) == 1:
        race = RACE_LABEL.get(game.opponents[0].race or "")
        return f"{names[0]} ({race})" if race else names[0]
    if len(names) == 2:
        return " & ".join(names)
    return f"{len(names)} opponents"


@dataclass
class _Last:
    game: SessionGame
    queue: int
    title: str
    body: str
    kind: str
    toast_id: str


class RecapService(QObject):
    def __init__(
        self,
        bus: EventBus,
        tracker: SessionTracker,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        super().__init__()
        self.bus = bus
        self.tracker = tracker
        self._now = now
        self._last: _Last | None = None
        tracker.game_added.connect(self.on_game_added)

    # ----------------------------------------------------------------- build
    @staticmethod
    def _h2h_suffix(game: SessionGame, profiles: Mapping[int, OpponentProfile]) -> str | None:
        """``You 2-1 vs Bob`` when the record including this game covers 2+ games."""
        if len(game.opponents) != 1:
            return None
        prof = profiles.get(0)
        prior = prof.h2h if prof is not None else None
        wins = (prior.wins if prior else 0) + (1 if game.my_result == "victory" else 0)
        losses = (prior.losses if prior else 0) + (1 if game.my_result == "defeat" else 0)
        games = (prior.games if prior else 0) + 1
        if games < H2H_MIN_GAMES:
            return None
        return f"You {wins}-{losses} vs {game.opponents[0].name}"

    def _spec(self, last: _Last, prefix: str = "") -> ToastSpec:
        return ToastSpec(
            last.title,
            prefix + last.body,
            kind=last.kind,  # type: ignore[arg-type]
            id=last.toast_id,
            duration_ms=RECAP_TOAST_MS,
        )

    @Slot(object, object, object)
    def on_game_added(
        self, game: SessionGame, result: GameResult, profiles: Mapping[int, OpponentProfile]
    ) -> None:
        if game.my_result not in ("victory", "defeat", "tie") or not game.opponents:
            return
        word = {"victory": "Victory", "defeat": "Defeat", "tie": "Tie"}[game.my_result]
        kind = {"victory": "win", "defeat": "loss", "tie": "info"}[game.my_result]
        snap = self.tracker.current()
        body = join(
            [
                duration(game.game_seconds),
                f"Session {snap.wins}-{snap.losses}" if snap.games else None,
                self._h2h_suffix(game, profiles),
            ]
        )
        last = _Last(
            game=game,
            queue=int(matching.queue_for(game.mode)),
            title=f"{word} vs {opponent_text(game)}",
            body=body or "",
            kind=kind,
            toast_id=f"recap-{result.context.game_id}",
        )
        self._last = last
        self.bus.toast_requested.emit(self._spec(last))

    @Slot(int, int)
    def on_mmr_refreshed(self, queue: int, rating: int) -> None:
        """Update the recap in place (or push it again if it already expired)."""
        last = self._last
        if last is None or last.queue != queue:
            return
        if self._now() - last.game.ended_at > MMR_WINDOW:
            return
        before = last.game.mmr_before
        delta = f"{rating - before:+d} MMR ({rating:,})" if before else f"{rating:,} MMR"
        prefix = f"{delta} · "
        if not last.body:
            prefix = prefix.removesuffix(" · ")
        self.bus.toast_requested.emit(self._spec(last, prefix))
