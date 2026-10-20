"""Filesystem locations, resolved through platformdirs.

Nothing here touches the disk at import time. Call ``ensure_dirs()`` from startup
code before writing logs, the database or the HTTP cache.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs

APP_NAME = "smurfsniper"
APP_AUTHOR = "smurfsniper"


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))


def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME, APP_AUTHOR))


def log_dir() -> Path:
    return Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))


def db_path() -> Path:
    """SQLite player log (head-to-head history)."""
    return data_dir() / "player_log.sqlite3"


def http_cache_path() -> Path:
    """SQLite tier of the HTTP response cache."""
    return cache_dir() / "http_cache.sqlite3"


def log_file() -> Path:
    return log_dir() / "app.log"


def ensure_dirs() -> None:
    """Create every app directory. Safe to call repeatedly."""
    for d in (config_dir(), data_dir(), cache_dir(), log_dir()):
        d.mkdir(parents=True, exist_ok=True)
