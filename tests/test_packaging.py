from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from smurfsniper._version import __version__
from smurfsniper.app import console
from smurfsniper.assets import asset_path

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location(
        "make_version_file", ROOT / "scripts" / "make_version_file.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_file_render():
    mod = load_script()
    text = mod.render("1.2.3")
    assert "filevers=(1, 2, 3, 0)" in text and "'ProductVersion', '1.2.3'" in text
    assert "filevers=(0, 0, 0, 0)" in mod.render("dev")
    assert "filevers=(2, 0, 0, 0)" in mod.render("2.0.0-rc.1")
    assert mod.read_version() == __version__


def test_version_file_written(tmp_path: Path):
    mod = load_script()
    out = tmp_path / "b" / "version_info.txt"
    assert mod.main([str(out)]) == 0
    assert f"'FileVersion', '{__version__}'" in out.read_text(encoding="utf-8")


def test_assets_load(qapp):
    for name in ("logo.ico", "logo.png", "tray.png"):
        assert asset_path(name).is_file(), name
    assert not QIcon(str(asset_path("tray.png"))).isNull()


def test_tray_icon_is_small(qapp):
    pm = QPixmap(str(asset_path("tray.png")))
    assert 16 <= pm.width() <= 64 and pm.width() == pm.height()


def test_spec_is_windowed_and_ships_assets():
    spec = (ROOT / "smurfsniper.spec").read_text(encoding="utf-8")
    assert "console=False" in spec
    assert '("smurfsniper/assets", "smurfsniper/assets")' in spec
    assert "version=VERSION_FILE" in spec
    # QtNetwork must stay excluded (QLockFile, not QLocalServer, guards single instance)
    assert '"PySide6.QtNetwork"' in spec


def test_entry_attaches_console_first():
    text = (ROOT / "packaging" / "pyi_entry.py").read_text(encoding="utf-8")
    assert text.index("attach_parent_console()") < text.index("    main()")


def test_attach_console_is_a_noop_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert console.attach_parent_console() is False


def test_attach_console_only_without_stdout(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["smurfsniper.exe", "--version"])
    called: list[int] = []
    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            kernel32=types.SimpleNamespace(AttachConsole=lambda pid: called.append(pid) or 0)
        )
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    monkeypatch.setattr(sys, "stdout", io.StringIO())  # has stdout: untouched
    assert console.attach_parent_console() is False and called == []
    monkeypatch.setattr(sys, "stdout", None)
    assert console.attach_parent_console() is False  # AttachConsole failed -> False
    assert called == [-1]


def test_logging_skips_console_sink_without_stderr(monkeypatch, tmp_dirs):
    from smurfsniper.logger import logger, setup_logging

    monkeypatch.setattr(sys, "stderr", None)
    setup_logging("INFO", console=True)  # must not raise with no stderr
    logger.info("hello windowed exe")
    logger.remove()
    assert (tmp_dirs["log"] / "app.log").exists()
