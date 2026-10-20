from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    """Load ``tests/fixtures/<name>.json`` (UTF-8)."""

    def _load(name: str) -> Any:
        return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Point every ``smurfsniper.paths`` user dir at ``tmp_path``."""
    from smurfsniper import paths

    dirs = {
        "config": tmp_path / "config",
        "data": tmp_path / "data",
        "cache": tmp_path / "cache",
        "log": tmp_path / "log",
    }
    monkeypatch.setattr(paths, "config_dir", lambda: dirs["config"])
    monkeypatch.setattr(paths, "data_dir", lambda: dirs["data"])
    monkeypatch.setattr(paths, "cache_dir", lambda: dirs["cache"])
    monkeypatch.setattr(paths, "log_dir", lambda: dirs["log"])
    return dirs
