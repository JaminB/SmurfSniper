# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file, console Windows build of smurfsniper.

Build:  pyinstaller --clean --noconfirm smurfsniper.spec
Output: dist/smurfsniper.exe (self-contained; no Python required on the target).

PySide6 is handled by PyInstaller's bundled Qt hooks. keyboard/peewee are listed
as hidden imports defensively.

frida is a declared project dependency but is NOT imported anywhere in the
source. Its native module (_frida.pyd, ~113 MB) is the single largest payload,
so it is excluded from the freeze. If frida ever gets used at runtime, drop it
from _EXCLUDES below (and it will be picked up automatically).

The app only uses QtCore/QtGui/QtWidgets, but the PySide6 hook drags in the
whole Qt distribution (QML, WebEngine, Quick, Multimedia, translations, the
software-OpenGL and ffmpeg fallbacks, ...). We exclude those unused Qt python
modules and post-filter the collected binaries/datas to drop their DLLs and
data trees. The Windows platform plugin (qwindows), styles, imageformats and
the ANGLE GL libs (libEGL/libGLESv2/d3dcompiler) are NOT in the denylist and
stay bundled.
"""

import os

# Unused Qt python submodules — keep PyInstaller from analyzing/collecting them.
_QT_EXCLUDES = [
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtRemoteObjects",
    "PySide6.QtHttpServer",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtNetworkAuth",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
]

# Substrings (matched case-insensitively against each collected file's bundle
# path) that identify the unused Qt payload to drop from binaries + datas.
_QT_DROP_SUBSTRINGS = [
    os.sep + "translations" + os.sep,  # Qt .qm translation files
    os.sep + "qml" + os.sep,           # entire QML tree
    "webengine",
    "qt6quick",
    "qt6qml",
    "qt63d",
    "qt6multimedia",
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6pdf",
    "qt6sql",
    "qt6designer",
    "qt6bluetooth",
    "qt6nfc",
    "qt6positioning",
    "qt6location",
    "qt6sensors",
    "qt6serial",
    "qt6spatialaudio",
    "qt6texttospeech",
    "qt6remoteobjects",
    "qt6httpserver",
    "qt6scxml",
    "qt6statemachine",
    "qt6networkauth",
    "opengl32sw",   # 20 MB software-OpenGL fallback; HW/ANGLE GL stays bundled
    "avcodec",      # ffmpeg libs — multimedia only, unused
    "avformat",
    "avutil",
    "swscale",
    "swresample",
]


def _keep(entry):
    dest = entry[0].lower()
    return not any(s in dest for s in _QT_DROP_SUBSTRINGS)


a = Analysis(
    ["packaging/pyi_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["keyboard", "peewee"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "frida", "_frida", *_QT_EXCLUDES],
    noarchive=False,
)

a.binaries = TOC([e for e in a.binaries if _keep(e)])
a.datas = TOC([e for e in a.datas if _keep(e)])

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
