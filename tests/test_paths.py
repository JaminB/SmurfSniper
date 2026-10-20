from __future__ import annotations

import importlib
from pathlib import Path


def test_import_has_no_side_effects(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import smurfsniper.logger
    import smurfsniper.paths

    importlib.reload(smurfsniper.paths)
    importlib.reload(smurfsniper.logger)
    assert list(tmp_path.iterdir()) == []


def test_ensure_dirs_creates_all(tmp_dirs):
    from smurfsniper import paths

    paths.ensure_dirs()
    for d in tmp_dirs.values():
        assert d.is_dir()
    assert paths.db_path().parent == tmp_dirs["data"]
    assert paths.http_cache_path().parent == tmp_dirs["cache"]


def test_setup_logging_writes_file(tmp_dirs):
    from smurfsniper.logger import logger, setup_logging

    setup_logging("DEBUG", console=False)
    logger.info("hello from test")
    logger.complete()
    logger.remove()
    assert (tmp_dirs["log"] / "app.log").read_text(encoding="utf-8").count("hello from test") == 1
