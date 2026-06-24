"""Config file discovery and write-location policy.

Resolution order: current working dir first, then the platformdirs user config
dir. New files default to the user config dir. Used by both the GUI prefill and
the headless load path.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "smurfsniper"
APP_AUTHOR = "smurfsniper"

# Prefer .yaml (the committed name); also accept the legacy .yml spelling.
CONFIG_FILENAMES = ("config.yaml", "config.yml")


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, APP_AUTHOR))


def candidate_dirs() -> list[Path]:
    return [Path.cwd(), config_dir()]


def find_config_file() -> Path | None:
    """First existing config file in cwd, then the user config dir. None if absent."""
    for directory in candidate_dirs():
        for name in CONFIG_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def default_write_path() -> Path:
    """Where to write a brand-new config: user_config_dir/config.yaml."""
    return config_dir() / CONFIG_FILENAMES[0]


def resolve_config(explicit: Path | None) -> tuple[Path | None, Path]:
    """Resolve (load_path_or_None, write_path).

    - explicit given & exists -> (explicit, explicit)
    - explicit given & missing -> (None, explicit)   # new file at requested path
    - no explicit              -> (found, found or default_write_path())
    """
    if explicit is not None:
        explicit = Path(explicit)
        if explicit.is_file():
            return explicit, explicit
        return None, explicit

    found = find_config_file()
    if found is not None:
        return found, found
    return None, default_write_path()
