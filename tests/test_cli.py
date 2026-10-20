from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from smurfsniper._version import __version__
from smurfsniper.api.cache import CacheEntry, DiskCache
from smurfsniper.cli import cli
from smurfsniper.models.config import Config, save_config


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    cfg = Config()
    cfg.integrations.aligulac_api_key = "supersecretkey1234"  # type: ignore[assignment]
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    return path


def invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_dry_run_with_override_prints_value(cfg_path):
    res = invoke("run", "--config", str(cfg_path), "--dry-run", "--set", "overlays.opacity=0.8")
    assert res.exit_code == 0, res.output
    assert "opacity: 0.8" in res.output
    assert "Config is valid" in res.output


def test_dry_run_url_maps_to_advanced(cfg_path):
    res = invoke("run", "--config", str(cfg_path), "--dry-run", "--url", "http://x:1/game")
    assert res.exit_code == 0, res.output
    assert "sc2_client_url: http://x:1" in res.output


def test_dry_run_does_not_save_overrides(cfg_path):
    before = cfg_path.read_text(encoding="utf-8")
    invoke("run", "--config", str(cfg_path), "--dry-run", "--set", "overlays.opacity=0.8")
    assert cfg_path.read_text(encoding="utf-8") == before


def test_validate_masks_the_key(cfg_path):
    res = invoke("validate", "--config", str(cfg_path), "--show")
    assert res.exit_code == 0, res.output
    assert "****1234" in res.output
    assert "supersecretkey1234" not in res.output


def test_dry_run_masks_the_key(cfg_path):
    res = invoke("run", "--config", str(cfg_path), "--dry-run")
    assert "supersecretkey1234" not in res.output and "****1234" in res.output


def test_validate_reports_bad_values(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\noverlays:\n  opacity: 9\n", encoding="utf-8")
    res = invoke("validate", "--config", str(bad))
    assert res.exit_code != 0 and "validation failed" in res.output.lower()


def test_unknown_override_is_an_error(cfg_path):
    res = invoke("run", "--config", str(cfg_path), "--dry-run", "--set", "nope.x=1")
    assert res.exit_code != 0 and "Unknown config key" in res.output


def test_validate_does_not_migrate_on_disk(tmp_path):
    v1 = tmp_path / "config.yaml"
    v1.write_text("me:\n  name: Hero\n  mmr: 4000\n", encoding="utf-8")
    res = invoke("validate", "--config", str(v1), "--show")
    assert res.exit_code == 0 and "name: Hero" in res.output
    assert "version" not in yaml.safe_load(v1.read_text(encoding="utf-8"))
    assert not (tmp_path / "config.v1.bak.yaml").exists()


def test_version_flags():
    for flag in ("--version", "-V"):
        res = invoke(flag)
        assert res.exit_code == 0 and __version__ in res.output


def test_cache_stats_and_clear(tmp_dirs):
    res = invoke("cache", "stats")
    assert res.exit_code == 0 and "0 entries" in res.output
    from smurfsniper import paths

    disk = DiskCache(paths.http_cache_path())
    disk.set("k", CacheEntry(body=b"x" * 2048, status=200, stored_at=1.0, expires_at=2e12))
    disk.close()
    res = invoke("cache", "stats")
    assert "1 entries" in res.output and "KB" in res.output
    res = invoke("cache", "clear")
    assert res.exit_code == 0
    assert "0 entries" in invoke("cache", "stats").output


def test_self_test_passes(tmp_path):
    out = tmp_path / "st.json"
    res = invoke("self-test", "--output", str(out))
    assert res.exit_code == 0, res.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] is True and data["version"] == __version__


def test_bare_command_runs_the_tray_app(monkeypatch, tmp_dirs):
    started: dict = {}

    class FakeApp:
        def __init__(self, config, path, *, tray=True, headless=False):
            started.update(config=config, path=path, tray=tray)

        def run(self):
            return 0

    monkeypatch.setattr("smurfsniper.app.application.SmurfSniperApp", FakeApp)
    monkeypatch.setattr("smurfsniper.logger.setup_logging", lambda *a, **k: None)
    res = invoke()
    assert res.exit_code == 0
    assert started["tray"] is True and isinstance(started["config"], Config)
    res = invoke("run", "--no-tray")
    assert res.exit_code == 0 and started["tray"] is False


def test_hidden_commands_not_in_help():
    assert "self-test" not in invoke("--help").output
