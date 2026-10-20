#!/usr/bin/env python3
"""Write the Windows version resource file PyInstaller embeds in the exe.

Usage: python scripts/make_version_file.py [OUTPUT]   (default: build/version_info.txt)
The version comes from smurfsniper/_version.py (maintained by release-please).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0),
    prodvers=({a}, {b}, {c}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'JaminB'),
         StringStruct('FileDescription', 'SmurfSniper - StarCraft II smurf detection overlay'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', 'smurfsniper'),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', 'smurfsniper.exe'),
         StringStruct('ProductName', 'SmurfSniper'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def read_version(root: Path = ROOT) -> str:
    text = (root / "smurfsniper" / "_version.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise ValueError("__version__ not found in smurfsniper/_version.py")
    return m.group(1)


def render(version: str) -> str:
    """The version-file text for ``version`` (``1.2.3`` or ``1.2.3-rc.1``)."""
    nums = [int(n) for n in re.findall(r"\d+", version.split("-")[0])][:3]
    a, b, c = (nums + [0, 0, 0])[:3]
    return TEMPLATE.format(a=a, b=b, c=c, version=version)


def write(version: str, output: str | Path) -> str:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(version), encoding="utf-8")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0]) if args else ROOT / "build" / "version_info.txt"
    write(read_version(), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
