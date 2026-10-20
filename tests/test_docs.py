"""The hotkey tables in README.md and CLAUDE.md must match the code."""

from __future__ import annotations

from pathlib import Path

import pytest

from smurfsniper.app.hotkeys import DEFAULT_BINDINGS, HotkeyAction, to_display
from smurfsniper.models.config import HotkeyConfig

ROOT = Path(__file__).resolve().parent.parent


def table_rows(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("|")]


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md"])
def test_default_hotkeys_are_documented(doc):
    rows = table_rows((ROOT / doc).read_text(encoding="utf-8"))
    for action, binding in DEFAULT_BINDINGS.items():
        shown = to_display(binding)
        assert any(shown in row for row in rows), f"{doc}: {shown} ({action.value})"


def test_claude_md_config_keys_match_the_hotkey_config():
    rows = table_rows((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    cfg = HotkeyConfig()
    for action in HotkeyAction:
        key = action.value
        assert hasattr(cfg, key), key
        assert any(f"`{key}`" in row for row in rows), key


def test_every_default_binding_matches_the_config_defaults():
    cfg = HotkeyConfig()
    for action, binding in DEFAULT_BINDINGS.items():
        assert getattr(cfg, action.value) == binding
