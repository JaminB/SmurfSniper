"""Global hotkeys: bindings, validation and the ``keyboard``-backed manager.

``keyboard`` callbacks run on its hook thread. They only debounce and emit
``HotkeyManager.triggered``; Qt queues the signal to the main thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

from smurfsniper.logger import logger
from smurfsniper.models.config import HotkeyConfig


class HotkeyAction(StrEnum):
    OPPONENT_CARD = "opponent_card"
    INTEL = "intel"
    SESSION = "session"
    RIVALS = "rivals"
    REDETECT = "redetect"
    HIDE_ALL = "hide_all"


ACTION_LABELS = {
    HotkeyAction.OPPONENT_CARD: "Opponent card",
    HotkeyAction.INTEL: "Scouting intel",
    HotkeyAction.SESSION: "Session tracker",
    HotkeyAction.RIVALS: "Rivals",
    HotkeyAction.REDETECT: "Re-detect game",
    HotkeyAction.HIDE_ALL: "Hide / show all",
}
DEFAULT_BINDINGS = {
    HotkeyAction.OPPONENT_CARD: "ctrl+shift+1",
    HotkeyAction.INTEL: "ctrl+shift+2",
    HotkeyAction.SESSION: "ctrl+shift+3",
    HotkeyAction.RIVALS: "ctrl+shift+4",
    HotkeyAction.REDETECT: "ctrl+shift+r",
    HotkeyAction.HIDE_ALL: "ctrl+shift+`",
}
SC2_DEFAULT_CONFLICTS = {
    "ctrl+f1",
    "ctrl+f2",
    "ctrl+f3",
    "f1",
    "f2",
    "f3",
    "f10",
    "tab",
    "ctrl+tab",
    "alt+tab",
    "ctrl+shift+tab",
    "backspace",
    "ctrl+backspace",
    "space",
    "ctrl+space",
    "escape",
    "enter",
    "ctrl+alt+f",
} | {f"{m}+{d}" for m in ("ctrl", "shift", "alt", "ctrl+alt", "shift+alt") for d in "0123456789"}
UNAVAILABLE_HINT = "Hotkeys unavailable: run as administrator if SC2 runs elevated."

_MODIFIERS = ("ctrl", "shift", "alt", "windows")
_MOD_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "win": "windows",
    "super": "windows",
    "cmd": "windows",
    "meta": "windows",
    "option": "alt",
}
_DEBOUNCE_S = 0.3
_CONTROL_GROUP_MODS = {"shift", "ctrl", "alt"}


@dataclass(frozen=True)
class BindingIssue:
    action: HotkeyAction
    level: Literal["error", "warning"]
    message: str


# ------------------------------------------------------------------ bindings
def _split(binding: str) -> tuple[list[str], str]:
    """(sorted modifiers, key) of a ``+``-joined binding, lowercased and de-aliased."""
    text = binding.strip().lower()
    plus_key = text.endswith("++")  # "ctrl++" -> the key is "+"
    parts = text[:-2].split("+") if plus_key else text.split("+")
    if plus_key:
        parts.append("+")
    parts = [_MOD_ALIASES.get(p.strip(), p.strip()) for p in parts if p.strip()]
    mods = sorted({p for p in parts if p in _MODIFIERS}, key=_MODIFIERS.index)
    keys = [p for p in parts if p not in _MODIFIERS]
    return mods, (keys[-1] if keys else "")


def normalize(binding: str) -> str:
    mods, key = _split(binding)
    return "+".join([*mods, key] if key else mods)


def to_display(binding: str) -> str:
    """``ctrl+shift+` `` -> ``Ctrl+Shift+` ``."""
    mods, key = _split(binding)
    names = [m.title() for m in mods]
    if key:
        names.append(key.upper() if len(key) <= 2 and key.isalnum() else key.title())
    return "+".join(names)


_SHIFTED = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}  # fmt: skip
_KEY_NAMES = {
    Qt.Key.Key_QuoteLeft: "`",
    Qt.Key.Key_Escape: "escape",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "tab",
}
_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
}


def from_qkeysequence(seq: QKeySequence) -> str | None:
    """First key combination as a ``keyboard``-library string, or None if unusable."""
    if seq.isEmpty() or seq.count() == 0:
        return None
    combo = seq[0]
    key = combo.key()
    if key in _MODIFIER_KEYS or key == Qt.Key.Key_unknown:
        return None
    mods = combo.keyboardModifiers()
    parts: list[str] = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("windows")
    name = _KEY_NAMES.get(key)
    if name is None:
        name = QKeySequence(key).toString().lower()
        if not name:
            return None
    if "shift" in parts and name in _SHIFTED:
        name = _SHIFTED[name]
    return "+".join([*parts, name])


def _keyboard() -> Any:
    import keyboard

    return keyboard


def validate_bindings(cfg: HotkeyConfig) -> list[BindingIssue]:
    """Errors (not registerable) and warnings (likely SC2 conflicts) for all bindings."""
    issues: list[BindingIssue] = []
    seen: dict[str, HotkeyAction] = {}
    try:
        kb = _keyboard()
    except Exception:  # no keyboard lib / no permission: parse check is skipped
        kb = None
    for action in HotkeyAction:
        raw = getattr(cfg, action.value)
        mods, key = _split(raw)
        norm = normalize(raw)
        if not key:
            issues.append(BindingIssue(action, "error", "Choose a key, not only modifiers."))
            continue
        if not mods:
            issues.append(BindingIssue(action, "error", "Add a modifier (Ctrl, Shift or Alt)."))
            continue
        if kb is not None:
            try:
                kb.parse_hotkey(norm)
            except Exception:
                issues.append(
                    BindingIssue(
                        action,
                        "error",
                        "This key is not available on your keyboard layout. Try another.",
                    )
                )
                continue
        if norm in seen:
            other = ACTION_LABELS[seen[norm]]
            issues.append(BindingIssue(action, "error", f"Already used by {other}."))
            continue
        seen[norm] = action
        if norm in SC2_DEFAULT_CONFLICTS or (
            len(mods) == 1 and mods[0] in _CONTROL_GROUP_MODS and key.isdigit()
        ):
            issues.append(
                BindingIssue(action, "warning", "SC2 uses this combo by default (control groups).")
            )
    return issues


# ------------------------------------------------------------------- manager
class HotkeyManager(QObject):
    triggered = Signal(str)  # HotkeyAction value, emitted from the keyboard thread

    def __init__(
        self,
        config: HotkeyConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__()
        self.config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._handles: list[Any] = []
        self._suspended = False
        self.unavailable = False

    # -------------------------------------------------------------- lifecycle
    def start(self) -> list[BindingIssue]:
        self._suspended = False
        return self._register()

    def apply(self, config: HotkeyConfig) -> list[BindingIssue]:
        self._unregister()
        self.config = config
        if self._suspended:
            return validate_bindings(config)
        return self._register()

    def suspend(self) -> None:
        """Release our hooks while the user records a new binding."""
        self._suspended = True
        self._unregister()

    def resume(self) -> None:
        if self._suspended:
            self._suspended = False
            self._register()

    def stop(self) -> None:
        self._unregister()

    # ---------------------------------------------------------------- internals
    def _register(self) -> list[BindingIssue]:
        self._unregister()
        if not self.config.enabled:
            return []
        try:
            kb = _keyboard()
        except (ImportError, OSError) as e:
            logger.warning(f"{UNAVAILABLE_HINT} ({e})")
            self.unavailable = True
            return [BindingIssue(a, "error", UNAVAILABLE_HINT) for a in HotkeyAction]
        issues = validate_bindings(self.config)
        failed = {i.action for i in issues if i.level == "error"}
        for action in HotkeyAction:
            if action in failed:
                continue
            binding = normalize(getattr(self.config, action.value))
            try:
                handle = kb.add_hotkey(
                    binding,
                    lambda a=action.value: self._fire(a),
                    suppress=False,
                    trigger_on_release=False,
                )
            except (ImportError, OSError) as e:
                logger.warning(f"{UNAVAILABLE_HINT} ({e})")
                self.unavailable = True
                issues.append(BindingIssue(action, "error", UNAVAILABLE_HINT))
                break
            except Exception as e:
                logger.warning(f"Could not register {binding}: {e}")
                issues.append(BindingIssue(action, "error", f"Could not register: {e}"))
                continue
            self._handles.append(handle)
        return issues

    def _unregister(self) -> None:
        handles, self._handles = self._handles, []
        if not handles:
            return
        try:
            kb = _keyboard()
            for h in handles:
                try:
                    kb.remove_hotkey(h)
                except Exception as e:
                    logger.debug(f"remove_hotkey failed: {e}")
        except Exception as e:
            logger.debug(f"unhook failed: {e}")

    def _fire(self, action: str) -> None:
        """Keyboard thread: debounce per action, then emit. Nothing else."""
        now = self._clock()
        with self._lock:
            last = self._last.get(action)
            if last is not None and now - last < _DEBOUNCE_S:
                return
            self._last[action] = now
        self.triggered.emit(action)
