from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr

from smurfsniper.models import config as cfgmod
from smurfsniper.models.config import (
    Anchor,
    Config,
    ConfigError,
    apply_overrides,
    load_config,
    mask_secret,
    masked_dump,
    save_config,
)


def test_defaults_round_trip(tmp_path: Path):
    path = tmp_path / "config.yaml"
    cfg = Config()
    save_config(cfg, path)
    loaded, got = load_config(path)
    assert got == path
    assert loaded == cfg
    assert loaded.overlays.card.placement.anchor is Anchor.TOP_CENTER
    assert loaded.hotkeys.hide_all == "ctrl+shift+`"


def test_missing_file_gives_defaults_and_is_not_written(tmp_path: Path):
    cfg, path = load_config(tmp_path / "nope.yaml")
    assert cfg == Config()
    assert not path.exists()


def test_round_trip_with_account_and_secret(tmp_path: Path):
    cfg = Config()
    cfg.account.name = "Hero"
    cfg.account.mmr_by_queue[201] = 4100
    cfg.integrations.aligulac_api_key = SecretStr("secretvalue1234")
    path = tmp_path / "c.yaml"
    save_config(cfg, path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["integrations"]["aligulac_api_key"] == "secretvalue1234"  # plain on disk
    loaded, _ = load_config(path)
    assert loaded.account.mmr_by_queue == {201: 4100}
    assert loaded.aligulac_key == "secretvalue1234"


def test_save_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []
    real = os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(cfgmod.os, "replace", spy)
    path = tmp_path / "sub" / "config.yaml"
    save_config(Config(), path)
    assert len(calls) == 1
    assert calls[0][1] == str(path) and calls[0][0] != str(path)
    assert not Path(calls[0][0]).exists()


def test_overrides_parse_types():
    cfg = apply_overrides(
        Config(),
        [
            "overlays.opacity=0.8",
            "advanced.ui_poll_ms=2000",
            "advanced.sounds_enabled=false",
            "account.mmr_override=4200",
            "overlays.card.placement.anchor=bottom_left",
            "account.name=Zed",
            "overlays.screen=null",
        ],
    )
    assert cfg.overlays.opacity == 0.8
    assert cfg.advanced.ui_poll_ms == 2000
    assert cfg.advanced.sounds_enabled is False
    assert cfg.account.mmr_override == 4200
    assert cfg.overlays.card.placement.anchor is Anchor.BOTTOM_LEFT
    assert cfg.account.name == "Zed"
    assert cfg.overlays.screen is None


def test_overrides_do_not_mutate_input_and_reject_bad_input():
    base = Config()
    apply_overrides(base, ["overlays.opacity=0.9"])
    assert base.overlays.opacity == 0.7
    with pytest.raises(ConfigError):
        apply_overrides(base, ["overlays.opacity=5"])  # out of range
    with pytest.raises(ConfigError):
        apply_overrides(base, ["nope.key=1"])
    with pytest.raises(ConfigError):
        apply_overrides(base, ["overlays.opacity"])


def test_override_queue_rating():
    cfg = apply_overrides(Config(), ["account.mmr_by_queue.201=3900"])
    assert cfg.account.mmr_for(201) == 3900


def test_secret_is_masked_in_dump():
    cfg = Config()
    cfg.integrations.aligulac_api_key = SecretStr("abcdef123456")
    dumped = masked_dump(cfg)
    assert dumped["integrations"]["aligulac_api_key"] == "****3456"
    assert "abcdef123456" not in yaml.dump(dumped)
    assert mask_secret(None) is None


def test_unknown_keys_are_ignored(tmp_path: Path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "version: 2\nfuture_thing: 1\naccount:\n  name: A\n  shiny: true\n", encoding="utf-8"
    )
    cfg, _ = load_config(path)
    assert cfg.account.name == "A"


def test_mmr_for_precedence():
    cfg = Config()
    assert cfg.account.mmr_for(202) is None
    cfg.account.mmr_by_queue = {201: 4000, 202: 3000}
    assert cfg.account.mmr_for(202) == 3000
    assert cfg.account.mmr_for(203) == 4000  # falls back to 1v1
    cfg.account.mmr_override = 5000
    assert cfg.account.mmr_for(202) == 5000


def test_bad_values_raise_config_error(tmp_path: Path):
    path = tmp_path / "c.yaml"
    path.write_text("version: 2\noverlays:\n  opacity: 9\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
