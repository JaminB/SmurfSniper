from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from click.testing import CliRunner

import smurfsniper
from smurfsniper._version import __version__
from smurfsniper.cli import cli


def _walk() -> list[str]:
    return sorted(
        m.name
        for m in pkgutil.walk_packages(smurfsniper.__path__, prefix="smurfsniper.")
        if m.name != "smurfsniper._modules"
    )


def test_import_every_module():
    names = _walk()
    assert names
    for name in names:
        importlib.import_module(name)


def test_self_test_command(tmp_path: Path):
    out = tmp_path / "selftest.json"
    result = CliRunner().invoke(cli, ["self-test", "--output", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["version"] == __version__
    assert data["modules"] > 0
    assert data["qt"]


def test_self_test_reports_failure(tmp_path: Path, monkeypatch):
    def boom() -> list[str]:
        raise RuntimeError("nope")

    monkeypatch.setattr("smurfsniper.cli._discover_modules", boom)
    out = tmp_path / "selftest.json"
    result = CliRunner().invoke(cli, ["self-test", "--output", str(out)])
    assert result.exit_code == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert "nope" in data["error"]


def test_self_test_is_hidden():
    result = CliRunner().invoke(cli, ["--help"])
    assert "self-test" not in result.output


def test_modules_list_complete():
    from smurfsniper._modules import MODULES

    assert list(MODULES) == _walk()
