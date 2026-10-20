from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_version", ROOT / "scripts" / "check_version.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_versions_agree():
    assert _load_script().check() == []


def test_tag_match_and_mismatch():
    mod = _load_script()
    v = mod.pyproject_version()
    assert mod.check(f"v{v}") == []
    assert mod.check("v999.0.0")


def test_detects_disagreement(tmp_path: Path):
    mod = _load_script()
    (tmp_path / "smurfsniper").mkdir()
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "smurfsniper" / "_version.py").write_text(
        '__version__ = "9.9.9"  # x-release-please-version\n', encoding="utf-8"
    )
    assert mod.check(root=tmp_path)
