"""Packaged static assets (icons). Load with ``asset_path`` so frozen builds work."""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def asset_path(name: str) -> Path:
    """Filesystem path of a packaged asset (works from source and from PyInstaller)."""
    with as_file(files(__package__).joinpath(name)) as p:
        return Path(p)
