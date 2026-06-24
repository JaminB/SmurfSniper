# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file, console Windows build of smurfsniper.

Build:  pyinstaller --clean --noconfirm smurfsniper.spec
Output: dist/smurfsniper.exe (self-contained; no Python required on the target).

PySide6 is handled by PyInstaller's bundled Qt hooks. frida/keyboard/peewee are
listed as hidden imports defensively; collect_all('frida') pulls its native
payload, which the static analysis can miss.
"""

from PyInstaller.utils.hooks import collect_all

frida_datas, frida_binaries, frida_hiddenimports = collect_all("frida")

a = Analysis(
    ["packaging/pyi_entry.py"],
    pathex=[],
    binaries=frida_binaries,
    datas=frida_datas,
    hiddenimports=["frida", "keyboard", "peewee", *frida_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="smurfsniper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
