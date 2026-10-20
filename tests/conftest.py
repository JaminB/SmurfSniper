from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

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
    monkeypatch.setattr(paths, "lock_path", lambda: tmp_path / "smurfsniper.lock")
    return dirs


LP_API = "https://liquipedia.net/starcraft2/api.php"
PULSE = "https://sc2pulse.nephest.com/sc2/api"


@pytest.fixture
def pulse(fixture_json):
    """respx router with recorded SC2Pulse + Liquipedia responses for a Serral 1v1."""
    with respx.mock(assert_all_called=False) as mock:
        routes = {
            "characters": mock.get(f"{PULSE}/characters").mock(
                return_value=httpx.Response(200, json=fixture_json("characters_query"))
            ),
            "teams": mock.get(f"{PULSE}/character-teams").mock(
                return_value=httpx.Response(200, json=fixture_json("character_teams"))
            ),
            "seasons": mock.get(f"{PULSE}/seasons").mock(
                return_value=httpx.Response(200, json=fixture_json("seasons"))
            ),
            "thresholds": mock.get(f"{PULSE}/tier-thresholds").mock(
                return_value=httpx.Response(200, json=fixture_json("tier_thresholds"))
            ),
            "histories": mock.get(f"{PULSE}/team-histories").mock(
                return_value=httpx.Response(200, json=fixture_json("team_histories"))
            ),
            "summaries": mock.get(f"{PULSE}/team-history-summaries").mock(
                return_value=httpx.Response(200, json=fixture_json("team_history_summaries"))
            ),
            "matches": mock.get(f"{PULSE}/character-matches").mock(
                return_value=httpx.Response(200, json=fixture_json("character_matches"))
            ),
            "entities": mock.get(f"{PULSE}/entities").mock(
                return_value=httpx.Response(200, json={"proPlayers": []})
            ),
            "links": mock.get(f"{PULSE}/character-links").mock(
                return_value=httpx.Response(200, json=fixture_json("character_links"))
            ),
            "liquipedia": mock.get(LP_API).mock(
                return_value=httpx.Response(200, json=fixture_json("liquipedia_query_extract"))
            ),
        }
        yield mock, routes
