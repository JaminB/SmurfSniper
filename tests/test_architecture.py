"""Layering rules from spec section 0, enforced by parsing imports with ``ast``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "smurfsniper"


def modules() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def rel(p: Path) -> str:
    return p.relative_to(PKG).as_posix()


def imports(path: Path) -> list[tuple[str, list[str]]]:
    """(module, imported names) for every import statement, including nested ones."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, []) for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, [a.name for a in node.names]))
    return out


def hits(mod: str, banned: tuple[str, ...]) -> bool:
    return any(mod == b or mod.startswith(b + ".") for b in banned)


RULES = {
    "analyze/": ("PySide6", "httpx", "keyboard", "peewee", "smurfsniper.ui"),
    "api/": ("PySide6", "smurfsniper.ui", "smurfsniper.analyze", "smurfsniper.core"),
    "models/": ("httpx", "smurfsniper.api.transport"),
}


@pytest.mark.parametrize("prefix,banned", sorted(RULES.items()))
def test_layer_imports(prefix, banned):
    bad = [
        f"{rel(p)}: {mod}"
        for p in modules()
        if rel(p).startswith(prefix)
        for mod, _ in imports(p)
        if hits(mod, banned)
    ]
    assert bad == []


def test_core_uses_only_qtcore():
    bad = [
        f"{rel(p)}: {mod}"
        for p in modules()
        if rel(p).startswith("core/")
        for mod, _ in imports(p)
        if (mod.startswith("PySide6") and mod != "PySide6.QtCore")
        or hits(mod, ("smurfsniper.ui", "keyboard"))
    ]
    assert bad == []


def test_widgets_only_in_ui_and_app():
    allowed = ("ui/", "app/")
    bad = []
    for p in modules():
        r = rel(p)
        if r.startswith(allowed) or r == "cli.py":  # cli: hidden self-test builds a QLabel
            continue
        for mod, names in imports(p):
            if mod == "PySide6.QtWidgets" and set(names) - {"QApplication"}:
                bad.append(f"{r}: {names}")
            if mod == "PySide6" and "QtWidgets" in names:
                bad.append(f"{r}: PySide6.QtWidgets")
    assert bad == []


def test_httpx_only_in_transport_and_sc2client():
    bad = [
        rel(p)
        for p in modules()
        for mod, _ in imports(p)
        if hits(mod, ("httpx",))
        and rel(p) != "api/transport.py"
        and not rel(p).startswith("api/sc2client/")
    ]
    assert bad == []


def test_dropped_scrapers_are_gone():
    for p in modules():
        text = p.read_text(encoding="utf-8")
        assert "gql.twitch.tv" not in text, rel(p)
        assert "youtube.com" not in text, rel(p)
    assert not (PKG / "api" / "cross_network.py").exists()


def test_no_naive_utcnow():
    for p in modules():
        text = p.read_text(encoding="utf-8")
        assert "utcnow(" not in text and "utcfromtimestamp(" not in text, rel(p)
