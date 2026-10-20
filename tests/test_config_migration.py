from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from smurfsniper.models.config import Anchor, load_config, migrate_v1

FIXTURE = Path(__file__).parent / "fixtures" / "config_v1.yaml"


def test_migrate_v1_mapping():
    cfg = migrate_v1(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))
    assert cfg.version == 2
    assert cfg.account.name == "Hero"
    assert cfg.account.mmr_by_queue == {201: 4200}
    assert cfg.account.teammates == ["Buddy", "Pal"]
    assert cfg.overlays.card.placement.anchor is Anchor.TOP_RIGHT
    assert cfg.overlays.card.auto_hide_seconds == 20
    assert cfg.aligulac_key == "ALIG-KEY-1234"


def test_unknown_anchor_falls_back_to_default():
    raw = {"me": {"name": "A", "mmr": 1}, "preferences": {"1v1_overlay": {"position": "nowhere"}}}
    assert migrate_v1(raw).overlays.card.placement.anchor is Anchor.TOP_CENTER


def test_load_migrates_writes_backup_and_drops_bedrock(tmp_path: Path):
    path = tmp_path / "config.yaml"
    shutil.copy(FIXTURE, path)
    original = path.read_bytes()
    cfg, _ = load_config(path)
    assert cfg.account.name == "Hero"
    backup = tmp_path / "config.v1.bak.yaml"
    assert backup.read_bytes() == original  # the v1 file is preserved untouched
    new_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(new_text)
    assert raw["version"] == 2 and "me" not in raw
    assert "aws_bedrock" not in new_text and "FAKE-SECRET" not in new_text
    again, _ = load_config(path)  # a second load is a plain v2 load
    assert again == cfg


def test_no_write_when_requested(tmp_path: Path):
    path = tmp_path / "config.yaml"
    shutil.copy(FIXTURE, path)
    cfg, _ = load_config(path, write_migration=False)
    assert cfg.account.name == "Hero"
    assert not (tmp_path / "config.v1.bak.yaml").exists()
    assert "me" in yaml.safe_load(path.read_text(encoding="utf-8"))
