"""SC2 client state machine (``/ui`` + ``/game``) and its polling QObject.

``GameStateMachine.next_state`` is pure: it takes the latest ``/ui`` and ``/game``
snapshots and returns the new state plus events. ``Sc2ClientPoller`` does the I/O
on its own QThread and emits Qt signals.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from smurfsniper.api.errors import ApiError, Unavailable
from smurfsniper.api.sc2client.models import GameInfo, GamePlayer, UiInfo
from smurfsniper.logger import logger

Mode = Literal["1v1", "2v2", "3v3", "4v4", "other"]
MyResult = Literal["victory", "defeat", "tie"]
_MODES: dict[int, Mode] = {2: "1v1", 4: "2v2", 6: "3v3", 8: "4v4"}
_RESULT = {"Victory": "victory", "Defeat": "defeat", "Tie": "tie"}
_INVERSE = {"victory": "defeat", "defeat": "victory", "tie": "tie"}


class GameState(StrEnum):
    OFFLINE = "offline"
    MENU = "menu"
    LOADING = "loading"
    IN_GAME = "in_game"
    REPLAY = "replay"
    RESULT = "result"


@dataclass(frozen=True)
class GameContext:
    game_id: int  # monotonically increasing per app run
    started_at: datetime
    players: tuple[GamePlayer, ...]  # humans + AI as reported
    me: GamePlayer | None
    allies: tuple[GamePlayer, ...]
    opponents: tuple[GamePlayer, ...]  # humans only
    mode: Mode
    vs_ai: bool


@dataclass(frozen=True)
class GameResult:
    context: GameContext
    my_result: MyResult | None
    display_time: float  # seconds


@dataclass(frozen=True)
class StateEvent:
    kind: Literal["state", "started", "ended"]
    payload: object


IdentifyMe = Callable[[Sequence[GamePlayer]], GamePlayer | None]


def _roster(players: Sequence[GamePlayer]) -> tuple[tuple[int, str], ...]:
    return tuple(sorted((p.id, p.name) for p in players))


def split_teams(
    players: Sequence[GamePlayer], me: GamePlayer | None, teammates: set[str]
) -> tuple[tuple[GamePlayer, ...], tuple[GamePlayer, ...]]:
    """(allies, opponents). Opponents are humans only.

    With ``me`` known in an even-sized team game, SC2 lists players team by team, so
    the half that contains me is my team. Configured teammates found in the other
    half override that guess (name-based split).
    """
    folded = {t.casefold() for t in teammates}
    humans = [p for p in players if p.is_human]
    if me is None:
        allies = tuple(p for p in humans if p.name.casefold() in folded)
        return allies, tuple(p for p in humans if p not in allies)

    n = len(players)
    if n >= 4 and n % 2 == 0:
        ordered = sorted(players, key=lambda p: p.id)
        half = n // 2
        mine = ordered[:half] if me in ordered[:half] else ordered[half:]
        theirs = [p for p in ordered if p not in mine]
        if not any(p.name.casefold() in folded for p in theirs if p.is_human):
            allies = tuple(p for p in mine if p != me)
            return allies, tuple(p for p in theirs if p.is_human)

    allies = tuple(p for p in players if p != me and p.name.casefold() in folded)
    opponents = tuple(p for p in humans if p != me and p not in allies)
    return allies, opponents


def derive_state(prev: GameState | None, ui: UiInfo | None, game: GameInfo | None) -> GameState:
    """State from one ``/ui`` + ``/game`` sample (``None`` = unavailable / not fetched)."""
    if ui is None and game is None:
        return GameState.OFFLINE
    if ui is not None and ui.active_screens:
        if ui.loading:
            return GameState.LOADING
        if (
            prev is GameState.IN_GAME
            and game is not None
            and game.players
            and not game.is_replay
            and not game.has_result
        ):
            # A screen over a running game (e.g. the in-game menu) is not a new game.
            return GameState.IN_GAME
        if (
            prev in (GameState.IN_GAME, GameState.RESULT)
            and game is not None
            and game.players
            and game.has_result
        ):
            return GameState.RESULT
        return GameState.MENU
    # No active screens (or /ui unavailable): judge by /game.
    if game is None:
        return GameState.MENU
    if game.is_replay:
        return GameState.REPLAY
    if game.players and game.has_result:
        return GameState.RESULT
    if game.players:
        return GameState.IN_GAME
    return GameState.MENU


def needs_game(prev: GameState | None, ui: UiInfo | None) -> bool:
    """Whether a tick should fetch ``/game`` after seeing ``ui``."""
    if ui is None or not ui.active_screens:
        return True
    return prev in (GameState.IN_GAME, GameState.RESULT) and not ui.loading


@dataclass
class GameStateMachine:
    identify_me: IdentifyMe
    teammates: Callable[[], set[str]]
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    state: GameState | None = None  # None until the first poll
    game_id: int = 0
    current: GameContext | None = None
    _ended: set[int] = field(default_factory=set)
    _force: bool = False

    def force_redetect(self) -> None:
        self._force = True

    def build_context(self, game: GameInfo) -> GameContext:
        players = tuple(game.players)
        humans = [p for p in players if p.is_human]
        me = self.identify_me(humans)
        allies, opponents = split_teams(players, me, self.teammates())
        vs_ai = any(not p.is_human for p in players)
        mode: Mode = "other" if vs_ai else _MODES.get(len(players), "other")
        self.game_id += 1
        return GameContext(
            game_id=self.game_id,
            started_at=self.now(),
            players=players,
            me=me,
            allies=allies,
            opponents=opponents,
            mode=mode,
            vs_ai=vs_ai,
        )

    @staticmethod
    def result_for(ctx: GameContext, game: GameInfo | None) -> MyResult | None:
        by_id = {p.id: p for p in (game.players if game else [])}
        if ctx.me is not None:
            me = by_id.get(ctx.me.id, ctx.me)
            if me.result in _RESULT:
                return _RESULT[me.result]
        for opp in ctx.opponents:
            p = by_id.get(opp.id, opp)
            if p.result in _RESULT:
                return _INVERSE[_RESULT[p.result]]
        return None

    def next_state(
        self, ui: UiInfo | None, game: GameInfo | None
    ) -> tuple[GameState, list[StateEvent]]:
        prev = self.state
        state = derive_state(prev, ui, game)
        events: list[StateEvent] = []

        roster_changed = (
            state is GameState.IN_GAME
            and prev is GameState.IN_GAME
            and self.current is not None
            and game is not None
            and _roster(game.players) != _roster(self.current.players)
        )
        if state is GameState.IN_GAME and (
            prev is not GameState.IN_GAME or self._force or roster_changed
        ):
            self._force = False
            assert game is not None
            self.current = self.build_context(game)
            events.append(StateEvent("started", self.current))

        if (
            state is GameState.RESULT
            and self.current is not None
            and self.current.game_id not in self._ended
        ):
            self._ended.add(self.current.game_id)
            events.append(
                StateEvent(
                    "ended",
                    GameResult(
                        context=self.current,
                        my_result=self.result_for(self.current, game),
                        display_time=game.display_time if game else 0.0,
                    ),
                )
            )

        if state is not prev:
            events.insert(0, StateEvent("state", state))
        self.state = state
        return state, events


class Sc2ClientPoller(QObject):
    """Polls the local SC2 client. Move to its own QThread; call ``start`` there."""

    state_changed = Signal(object)  # GameState
    game_started = Signal(object)  # GameContext
    game_ended = Signal(object)  # GameResult

    def __init__(
        self,
        client,
        identify_me: IdentifyMe,
        teammates: Callable[[], set[str]],
        *,
        ui_interval_ms: int = 1500,
        offline_interval_ms: int = 10000,
    ):
        super().__init__()
        self.client = client
        self.machine = GameStateMachine(identify_me=identify_me, teammates=teammates)
        self.ui_interval_ms = ui_interval_ms
        self.offline_interval_ms = offline_interval_ms
        self._timer: QTimer | None = None
        self._ui_supported = True

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.tick)
        self._timer.start(0)

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @Slot()
    def force_redetect(self) -> None:
        """The next IN_GAME poll re-emits ``game_started`` with a new ``game_id``."""
        self.machine.force_redetect()

    def _sample(self) -> tuple[UiInfo | None, GameInfo | None]:
        ui: UiInfo | None = None
        try:
            ui = self.client.ui()
        except Unavailable:
            ui = None
        except ApiError as e:  # e.g. 404 on builds without /ui: use /game only
            logger.debug(f"/ui unusable ({e}); falling back to /game")
            ui = None
        game: GameInfo | None = None
        if needs_game(self.machine.state, ui):
            try:
                game = self.client.game()
            except ApiError:
                game = None
        return ui, game

    @Slot()
    def tick(self) -> None:
        try:
            ui, game = self._sample()
            _, events = self.machine.next_state(ui, game)
            for ev in events:
                if ev.kind == "state":
                    if ev.payload is GameState.OFFLINE:
                        logger.info("SC2 client offline")
                    else:
                        logger.info(f"SC2 state: {ev.payload}")
                    self.state_changed.emit(ev.payload)
                elif ev.kind == "started":
                    self.game_started.emit(ev.payload)
                elif ev.kind == "ended":
                    self.game_ended.emit(ev.payload)
        except Exception as e:  # never let the poll loop die
            logger.exception(f"SC2 poll failed: {e}")
        finally:
            if self._timer is not None:
                offline = self.machine.state is GameState.OFFLINE
                self._timer.start(self.offline_interval_ms if offline else self.ui_interval_ms)
