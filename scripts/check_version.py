#!/usr/bin/env python3
"""Assert pyproject.toml, smurfsniper/_version.py (and optionally a tag) agree."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pyproject_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def module_version(root: Path = ROOT) -> str:
    text = (root / "smurfsniper" / "_version.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise ValueError("__version__ not found in smurfsniper/_version.py")
    return m.group(1)


def check(tag: str = "", root: Path = ROOT) -> list[str]:
    """Return a list of mismatch messages (empty when everything agrees)."""
    problems: list[str] = []
    py, mod = pyproject_version(root), module_version(root)
    if py != mod:
        problems.append(f"pyproject.toml version {py!r} != _version.py {mod!r}")
    if tag:
        want = tag[1:] if tag.startswith("v") else tag
        if want != py:
            problems.append(f"tag {tag!r} does not match version {py!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default="", help="release tag to compare (leading v is stripped)")
    args = ap.parse_args(argv)
    problems = check(args.tag)
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if not problems:
        print(f"version ok: {pyproject_version()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
