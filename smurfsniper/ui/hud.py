"""``HudController``: owns every overlay surface and applies the visibility rules.

Inputs (all delivered on the main thread):
- ``EventBus``: game state, game start/end, toast requests, config changes;
- ``LookupPipeline.update``: progressive opponent data (drives the card);
- hotkeys routed by the app (``on_hotkey``).

"Auto" surfaces (card, hint, toasts) follow the game state; hotkey panels always work.
Re-showing anything uses cached profiles only, never the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from smurfsniper.app.hotkeys import ACTION_LABELS, HotkeyAction, to_display
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult, GameState
from smurfsniper.core.lookup import TEAM_SLOT, LookupPipeline
from smurfsniper.core.profile import GameSeed, LookupUpdate, OpponentProfile, Stage
from smurfsniper.logger import logger
from smurfsniper.models.config import Config
from smurfsniper.ui import preview_data
from smurfsniper.ui.overlay import (
    HotkeyHint,
    OpponentCard,
    OverlayWindow,
    Panel,
    PanelHost,
    ToastSpec,
    ToastStack,
)
from smurfsniper.ui.overlay.card import race_accent
from smurfsniper.ui.panels.intel import build_intel_body, links_of
from smurfsniper.ui.tokens import TokenContext

RECENT = timedelta(minutes=10)  # how long the last game's card/intel stays reachable
SHORT_HINT_AFTER = 5  # from the 6th game of a run the hint only shows hide + card
PREVIEW_MS = 8000
INTEL_TITLE = "Scouting intel"
HINT_LABELS = {
    HotkeyAction.OPPONENT_CARD: "card",
    HotkeyAction.INTEL: "intel",
    HotkeyAction.SESSION: "session",
    HotkeyAction.RIVALS: "rivals",
    HotkeyAction.HIDE_ALL: "hide",
}
QUIET_STATES = (GameState.OFFLINE, GameState.MENU, GameState.LOADING, GameState.RESULT)


@dataclass(frozen=True)
class PanelSpec:
    title: str
    build_body: Callable[[], list[QWidget] | None]
    ensure: Callable[[], None] | None = None


def _on_main_thread() -> bool:
    app = QCoreApplication.instance()
    return app is None or QThread.currentThread() is app.thread()


class HudController(QObject):
    hidden_changed = Signal(bool)
    links_changed = Signal(list)  # [(label, url)] for the tray's "Last opponent links"

    def __init__(
        self,
        bus: EventBus,
        pipeline: LookupPipeline,
        config: Config,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        chime: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.bus = bus
        self.pipeline = pipeline
        self.config = config
        self._now = now
        self._chime = chime
        ov = config.overlays
        self.tokens = TokenContext.from_overlays(ov)
        self.card = OpponentCard(self.tokens, ov.card.placement, now=now)
        self.toasts = ToastStack(
            self.tokens,
            ov.toasts.placement,
            max_visible=ov.toasts.max_visible,
            seconds=ov.toasts.seconds,
        )
        self.hint = HotkeyHint(self.tokens, ov.hint.placement)
        self.panels = PanelHost()
        self._panel_specs: dict[str, PanelSpec] = {}

        self.state: GameState | None = None
        self.ctx: GameContext | None = None
        self.game_id: int | None = None
        self.profiles: dict[int, OpponentProfile] = {}
        self.team = None
        self.hud_hidden = False
        self.games_seen = 0
        self.dropped = 0
        self._left_game_at: datetime | None = None
        self._card_auto_done = False
        self._pulse_warned = False
        self._alerted: set[int] = set()
        self._intel_pending = False
        self._previews: list[QWidget] = []

        self._card_timer = QTimer(self)
        self._card_timer.setSingleShot(True)
        self._card_timer.timeout.connect(self._auto_hide_card)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self.hint.dismiss)
        self.card.changed.connect(self._on_card_changed)

        bus.state_changed.connect(self.on_state)
        bus.game_started.connect(self.on_game_started)
        bus.game_ended.connect(self.on_game_ended)
        bus.toast_requested.connect(self.on_toast)
        bus.config_changed.connect(self.on_config)
        pipeline.update.connect(self.on_update)

    # ------------------------------------------------------------- helpers
    def surfaces(self) -> list[OverlayWindow]:
        out: list[OverlayWindow] = [self.card, self.toasts, self.hint]
        if self.panels.panel is not None:
            out.append(self.panels.panel)
        return out

    def hotkey(self, action: HotkeyAction) -> str:
        return to_display(getattr(self.config.hotkeys, action.value))

    def game_active(self) -> bool:
        return self.state is GameState.IN_GAME and self.ctx is not None

    def recent(self) -> bool:
        """The current game, or the last one if it ended under 10 minutes ago."""
        if self.game_id is None:
            return False
        if self.game_active() or self._left_game_at is None:
            return True
        return self._now() - self._left_game_at < RECENT

    def _auto_allowed(self) -> bool:
        if self.hud_hidden:
            return False
        if self.state is GameState.REPLAY:
            return self.config.overlays.show_in_replays
        return self.state in (None, GameState.IN_GAME)

    def _check_thread(self) -> None:
        if __debug__:
            assert _on_main_thread(), "HudController slots must run on the GUI thread"

    # ---------------------------------------------------------------- slots
    @Slot(object)
    def on_state(self, s: GameState) -> None:
        self._check_thread()
        prev, self.state = self.state, s
        if s is GameState.IN_GAME:
            for w in self.surfaces():
                w.reassert_topmost()
            return
        if prev is GameState.IN_GAME and self.game_id is not None:
            self._left_game_at = self._now()
        if s in QUIET_STATES or (
            s is GameState.REPLAY and not self.config.overlays.show_in_replays
        ):
            self._card_timer.stop()
            self.card.dismiss()
            self._hint_timer.stop()
            self.hint.dismiss()

    @Slot(object)
    def on_game_started(self, ctx: GameContext) -> None:
        self._check_thread()
        self.reset_for_new_game()
        self.ctx = ctx
        self.game_id = ctx.game_id
        self.games_seen += 1
        self.profiles = {
            i: OpponentProfile(seed=GameSeed(p.name, p.race_code))
            for i, p in enumerate(ctx.opponents)
        }
        my_race = ctx.me.race_code if ctx.me is not None else None
        self.card.start(ctx.game_id, [p.seed for p in self.profiles.values()], my_race=my_race)
        self._show_hint()

    @Slot(object)
    def on_update(self, u: LookupUpdate) -> None:
        self._check_thread()
        if u.game_id != self.game_id:
            ctx = self.pipeline.context()
            newer = self.game_id is None or u.game_id > self.game_id
            if newer and ctx is not None and ctx.game_id == u.game_id:
                self.on_game_started(ctx)  # pipeline signalled before the bus reached us
            else:
                self.dropped += 1
                return
        if u.slot == TEAM_SLOT:
            self.team = u.data
            self.card.apply(u)
            return
        prof = self.profiles.get(u.slot)
        if prof is None:
            return
        prof.apply(u)
        self.card.apply(u)
        if u.stage is Stage.GAME:
            self._auto_reveal_card()
        elif u.stage is Stage.IDENTITY and u.error and not self._pulse_warned:
            self._pulse_warned = True
            self.on_toast(
                ToastSpec(
                    "SC2Pulse unreachable",
                    "Opponent stats unavailable this game.",
                    kind="warning",
                    id="pulse-down",
                )
            )
        elif u.stage is Stage.SMURF and u.data is not None:
            self._smurf_alert(u.slot, prof)
        if u.stage is Stage.INTEL and u.data is not None:
            self.links_changed.emit(links_of(list(self.profiles.values())))
        if u.stage in (Stage.IDENTITY, Stage.INTEL, Stage.TENDENCIES):
            self._refresh_intel()

    @Slot(object)
    def on_game_ended(self, r: GameResult) -> None:
        self._check_thread()
        if r.context.game_id == self.game_id:
            self._left_game_at = self._now()

    @Slot(str)
    def on_hotkey(self, action: str) -> None:
        self._check_thread()
        act = HotkeyAction(action)
        if act is HotkeyAction.HIDE_ALL:
            self.set_hidden(not self.hud_hidden)
        elif act is HotkeyAction.OPPONENT_CARD:
            self.toggle_card()
        elif act is HotkeyAction.INTEL:
            self.toggle_intel()
        elif act.value in self._panel_specs:
            self.toggle_panel(act)
        else:
            logger.info(f"{ACTION_LABELS.get(act, act.value)}: available in a later version")

    @Slot(object)
    def on_toast(self, spec: ToastSpec) -> None:
        self._check_thread()
        if not self.config.overlays.toasts.enabled or self.hud_hidden:
            return
        if self.state is GameState.REPLAY:
            return
        self.toasts.push(spec)

    @Slot(object)
    def on_config(self, cfg: Config) -> None:
        self._check_thread()
        self.config = cfg
        ov = cfg.overlays
        tokens = TokenContext.from_overlays(ov)
        self.card.placement = ov.card.placement
        self.toasts.placement = ov.toasts.placement
        self.hint.placement = ov.hint.placement
        self.toasts.set_limits(max_visible=ov.toasts.max_visible, seconds=ov.toasts.seconds)
        if tokens != self.tokens:
            self.tokens = tokens
            self.card.set_tokens(tokens)
            self.toasts.set_tokens(tokens)
            self.hint.set_tokens(tokens)
        else:
            for w in (self.card, self.toasts, self.hint):
                w.reposition()
        if ov.card.auto_hide_seconds <= 0:
            self._card_timer.stop()
        if not ov.toasts.enabled:
            self.toasts.clear()
        if not ov.hint.enabled:
            self.hint.dismiss()
        key = self.panels.key
        if key is not None and self.panels.current() is not None:
            self.panels.hide()  # rebuild at the new size / place
            self.on_hotkey(key)

    # -------------------------------------------------------------- actions
    def register_panel(
        self,
        action: HotkeyAction,
        title: str,
        build_body: Callable[[], list[QWidget] | None],
        *,
        ensure: Callable[[], None] | None = None,
    ) -> None:
        """Make ``action``'s hotkey toggle a panel (branch 5: session, rivals)."""
        self._panel_specs[action.value] = PanelSpec(title, build_body, ensure)

    def registered(self, action: HotkeyAction) -> bool:
        return (
            action
            in (
                HotkeyAction.OPPONENT_CARD,
                HotkeyAction.INTEL,
                HotkeyAction.HIDE_ALL,
            )
            or action.value in self._panel_specs
        )

    def set_hidden(self, hidden: bool) -> None:
        """Hide-all: dismiss every surface; nothing auto-shows until it is cleared."""
        changed = hidden != self.hud_hidden
        self.hud_hidden = hidden
        if hidden:
            self._card_timer.stop()
            self._hint_timer.stop()
            self.card.dismiss()
            self.hint.dismiss()
            self.panels.hide()
            self.toasts.clear()
        if changed:
            self.hidden_changed.emit(hidden)

    def dismiss_all(self) -> None:
        """Pause / quit: close everything without touching hide-all."""
        self._card_timer.stop()
        self._hint_timer.stop()
        for w in (self.card, self.hint):
            w.dismiss()
        self.panels.hide()

    def toggle_card(self) -> None:
        self.set_hidden(False)
        if self.card.shown:
            self._card_timer.stop()
            self.card.dismiss()
            return
        if self.card.sections and self.recent():
            self.card.reveal()
            self._arm_card_timer()
            return
        self.on_toast(
            ToastSpec(
                "No opponent yet",
                "The card appears when a ladder game starts.",
                id="no-opponent",
                chip=self.hotkey(HotkeyAction.OPPONENT_CARD),
            )
        )

    def toggle_intel(self) -> None:
        self.set_hidden(False)
        if self.panels.current(HotkeyAction.INTEL.value) is not None:
            self.panels.hide()
            return
        if not self.profiles or not self.recent():
            self._no_intel()
            return
        pending = self._request_intel()
        body = build_intel_body(list(self.profiles.values()), self.tokens)
        if body is None and not pending:
            self._no_intel()
            return
        self._intel_pending = pending

        def build() -> Panel:
            panel = self._make_panel(HotkeyAction.INTEL, INTEL_TITLE)
            if body is not None:
                panel.set_body(body)
            else:
                panel.set_loading("Looking up scouting intel…")
            return panel

        self.panels.toggle(HotkeyAction.INTEL.value, build)

    def toggle_panel(self, action: HotkeyAction) -> None:
        self.set_hidden(False)
        spec = self._panel_specs[action.value]
        if self.panels.current(action.value) is not None:
            self.panels.hide()
            return
        body = spec.build_body()
        if body is None and spec.ensure is None:
            self.on_toast(ToastSpec(f"{spec.title}: nothing yet", id=f"empty-{action.value}"))
            return
        if body is None and spec.ensure is not None:
            spec.ensure()

        def build() -> Panel:
            panel = self._make_panel(action, spec.title)
            if body is not None:
                panel.set_body(body)
            else:
                panel.set_loading()
            return panel

        self.panels.toggle(action.value, build)

    def refresh_panel(self, action: HotkeyAction) -> None:
        """Rebuild an open registered panel's body (e.g. after its data arrived)."""
        panel = self.panels.current(action.value)
        spec = self._panel_specs.get(action.value)
        if panel is None or spec is None:
            return
        body = spec.build_body()
        if body is not None:
            panel.set_body(body)

    def reset_for_new_game(self) -> None:
        """Stop every pending timer and clear per-game state (fixes delayed-show leaks)."""
        self._card_timer.stop()
        self._hint_timer.stop()
        self.card.hide_now()
        self.card.clear()
        self.hint.hide_now()
        self.panels.hide()
        self.toasts.clear()
        self.profiles = {}
        self.team = None
        self.ctx = None
        self.game_id = None
        self._left_game_at = None
        self._card_auto_done = False
        self._pulse_warned = False
        self._alerted = set()
        self._intel_pending = False
        if self.hud_hidden:
            self.hud_hidden = False
            self.hidden_changed.emit(False)

    def preview(self, config: Config | None = None) -> None:
        """Settings "Preview on screen": a sample card, toast and panel for 8 seconds."""
        cfg = config or self.config
        ov = cfg.overlays
        tk = TokenContext.from_overlays(ov)
        for w in self._previews:
            w.deleteLater()
        prof = preview_data.smurf_profile()
        card = OpponentCard(tk, ov.card.placement, now=lambda: preview_data.NOW)
        card.start(0, [prof.seed], my_race="ZERG")
        for u in preview_data.updates_for(0, 0, prof):
            card.apply(u)
        stack = ToastStack(tk, ov.toasts.placement, seconds=PREVIEW_MS / 1000)
        stack.push(ToastSpec("Preview: toast", "Recaps and alerts appear here.", kind="info"))
        panel = Panel(INTEL_TITLE, self.hotkey(HotkeyAction.INTEL), tk, ov.panels.placement)
        panel.set_body(build_intel_body([preview_data.intel_profile()], tk) or [])
        self._previews = [card, stack, panel]
        card.reveal()
        panel.reveal()

        def done() -> None:
            for w in self._previews:
                if isinstance(w, OverlayWindow):
                    w.dismiss(then=w.deleteLater)
            self._previews = []

        QTimer.singleShot(PREVIEW_MS, self, done)

    # ------------------------------------------------------------ internals
    def _make_panel(self, action: HotkeyAction, title: str) -> Panel:
        accent = None
        if action is HotkeyAction.INTEL and len(self.profiles) == 1:
            accent = race_accent(next(iter(self.profiles.values())).seed.race)
        return Panel(
            title,
            self.hotkey(action),
            self.tokens,
            self.config.overlays.panels.placement,
            accent,
        )

    def _show_hint(self) -> None:
        hint = self.config.overlays.hint
        if not hint.enabled or self.hud_hidden or not self.config.hotkeys.enabled:
            return
        if self.state not in (None, GameState.IN_GAME):
            return
        actions = [a for a in HINT_LABELS if self.registered(a)]
        if self.games_seen > SHORT_HINT_AFTER:
            actions = [HotkeyAction.HIDE_ALL, HotkeyAction.OPPONENT_CARD]
        self.hint.set_items([(self.hotkey(a), HINT_LABELS[a]) for a in actions])
        self.hint.reveal()
        self._hint_timer.start(max(1, round(hint.seconds * 1000)))

    def _auto_reveal_card(self) -> None:
        if self._card_auto_done or not self.card.sections:
            return
        if not self.config.overlays.card.enabled or not self._auto_allowed():
            return
        self._card_auto_done = True
        self.card.reveal()
        self._arm_card_timer()

    def _arm_card_timer(self) -> None:
        secs = self.config.overlays.card.auto_hide_seconds
        if secs > 0:
            self._card_timer.start(secs * 1000)
        else:
            self._card_timer.stop()

    def _on_card_changed(self) -> None:
        if self.card.shown:
            self._arm_card_timer()  # auto-hide counts from the last row change

    def _auto_hide_card(self) -> None:
        self.card.dismiss()

    def _smurf_alert(self, slot: int, prof: OpponentProfile) -> None:
        if slot in self._alerted or prof.smurf is None:
            return
        a = prof.smurf.assessment
        if a.level not in ("likely", "possible"):
            return
        self._alerted.add(slot)
        if self._chime is not None and not self.hud_hidden:
            self._chime("two" if a.level == "likely" else "one")
        if a.level == "likely" and not self.card.shown:
            name = prof.identity.character.base_name if prof.identity else prof.seed.name
            reason = a.top_reason.text if a.top_reason else None
            self.on_toast(
                ToastSpec(
                    f"{name}: likely smurf",
                    reason,
                    kind="danger",
                    id=f"smurf-{slot}",
                    chip=self.hotkey(HotkeyAction.OPPONENT_CARD),
                )
            )

    def _request_intel(self) -> bool:
        """Ask the pipeline for INTEL/TENDENCIES where missing; True if any is in flight."""
        gid = self.game_id
        if gid is None or self.pipeline.game_id != gid:
            return False
        pending = False
        for slot, prof in self.profiles.items():
            if prof.done(Stage.IDENTITY) and prof.identity is None:
                continue
            for stage in (Stage.INTEL, Stage.TENDENCIES):
                if not prof.done(stage):
                    self.pipeline.ensure(gid, slot, stage)
                    pending = True
        return pending

    def _intel_in_flight(self) -> bool:
        if self.game_id is None or self.pipeline.game_id != self.game_id:
            return False
        for prof in self.profiles.values():
            if not prof.done(Stage.IDENTITY):
                return True
            if prof.identity is not None and not (
                prof.done(Stage.INTEL) and prof.done(Stage.TENDENCIES)
            ):
                return True
        return False

    def _refresh_intel(self) -> None:
        panel = self.panels.current(HotkeyAction.INTEL.value)
        if panel is None:
            return
        body = build_intel_body(list(self.profiles.values()), self.tokens)
        if body is not None:
            panel.set_body(body)
            return
        if not self._intel_in_flight():
            self.panels.hide()
            self._no_intel()

    def _no_intel(self) -> None:
        self.on_toast(
            ToastSpec(
                "No intel yet",
                "Nothing public is known about this opponent.",
                id="no-intel",
                chip=self.hotkey(HotkeyAction.INTEL),
            )
        )
