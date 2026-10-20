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
    """Point platformdirs user dirs at ``tmp_path``.

    ``smurfsniper.paths`` does not exist yet (added with the API client layer); until
    then this patches platformdirs directly so tests never touch real user dirs.
    """
    import platformdirs

    dirs = {
        "config": tmp_path / "config",
        "data": tmp_path / "data",
        "cache": tmp_path / "cache",
        "log": tmp_path / "log",
    }
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *a, **k: str(dirs["config"]))
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **k: str(dirs["data"]))
    monkeypatch.setattr(platformdirs, "user_cache_dir", lambda *a, **k: str(dirs["cache"]))
    monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **k: str(dirs["log"]))
    return dirs
