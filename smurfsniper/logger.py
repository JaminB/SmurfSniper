"""Logging setup.

Import ``logger`` anywhere. Nothing is configured at import time (no sinks are
added and no directories are created); the CLI calls ``setup_logging`` once at
startup.
"""

from __future__ import annotations

import sys

from loguru import logger

from smurfsniper import paths

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"


def setup_logging(level: str = "INFO", *, console: bool = True) -> None:
    """Replace all sinks: a rotating file in ``user_log_dir`` plus optional console.

    The console sink is skipped when ``sys.stderr`` is None (windowed exe).
    """
    logger.remove()
    if console and sys.stderr is not None:
        logger.add(sys.stderr, colorize=True, format=_CONSOLE_FORMAT, level=level)
    try:
        paths.log_dir().mkdir(parents=True, exist_ok=True)
        logger.add(
            paths.log_file(),
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            format=_FILE_FORMAT,
            level=level,
            enqueue=True,
        )
    except OSError as e:  # read-only profile etc.: keep running with console only
        logger.warning(f"File logging disabled: {e}")


__all__ = ["logger", "setup_logging"]
