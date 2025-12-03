# smurf_sniper/logger.py

import sys
from pathlib import Path

from loguru import logger

LOG_PATH = Path("logs")
LOG_PATH.mkdir(exist_ok=True)

logger.remove()

logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>",
    level="INFO",
)

# Rotating file output
logger.add(
    LOG_PATH / "app.log",
    rotation="10 MB",
    retention="14 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    level="DEBUG",
)

__all__ = ["logger"]
