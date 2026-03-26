"""Logging setup for git-pulse.

Provides file logging (with rotation) and optional Rich console output.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from git_pulse.config import CONFIG_DIR


LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "git-pulse.log"

MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

_configured = False


def setup_logging(level: str = "INFO", console: bool = True) -> logging.Logger:
    """Configure and return the root git-pulse logger.

    Called once at startup. Subsequent calls return the existing logger.
    """
    global _configured

    logger = logging.getLogger("git_pulse")

    if _configured:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    if console:
        rich_handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
        )
        rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.addHandler(rich_handler)

    _configured = True
    return logger


def reset_logging() -> None:
    """Remove all handlers and reset the configured flag.

    Primarily useful in tests that need a fresh logger between runs.
    """
    global _configured
    logger = logging.getLogger("git_pulse")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    _configured = False


def get_logger() -> logging.Logger:
    return logging.getLogger("git_pulse")
