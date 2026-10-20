from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "render_preview.py"


def load():
    spec = importlib.util.spec_from_file_location("render_preview", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_render_preview_writes_pngs(qtbot, tmp_path):
    mod = load()
    assert mod.main(["--out", str(tmp_path)]) == 0
    names = {p.name for p in tmp_path.glob("*.png")}
    for comp in [*mod.COMPONENTS, "hud"]:
        for scale in ("1", "1.25"):
            assert f"{comp}@{scale}.png" in names
    assert all(p.stat().st_size > 0 for p in tmp_path.glob("*.png"))


def test_render_preview_only(qtbot, tmp_path):
    mod = load()
    mod.main(["--out", str(tmp_path), "--only", "card_t0"])
    assert sorted(p.name for p in tmp_path.glob("*.png")) == ["card_t0@1.25.png", "card_t0@1.png"]
