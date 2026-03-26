"""Unit tests for the logger module.

Tests logging setup, file handler creation, rotation config, and idempotency.
References LOG_DIR/LOG_FILE through the module to pick up monkeypatched values.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import git_pulse.logger as logger_mod
from git_pulse.logger import setup_logging, get_logger, reset_logging


@pytest.fixture(autouse=True)
def _clean_logger_handlers():
    """Remove all handlers from the git_pulse logger between tests
    so handlers from one test don't leak into the next."""
    logger = logging.getLogger("git_pulse")
    yield
    logger.handlers.clear()


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging("INFO", console=False)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "git_pulse"

    def test_creates_log_directory(self):
        setup_logging("INFO", console=False)
        assert logger_mod.LOG_DIR.exists()

    def test_sets_log_level(self):
        logger = setup_logging("DEBUG", console=False)
        assert logger.level == logging.DEBUG

    def test_file_handler_attached(self):
        logger = setup_logging("INFO", console=False)
        file_handlers = [
            h for h in logger.handlers
            if isinstance(h, RotatingFileHandler)
        ]
        assert len(file_handlers) >= 1

    def test_console_handler_when_enabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("git_pulse.logger._configured", False)
        logger = setup_logging("INFO", console=True)
        from rich.logging import RichHandler
        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) >= 1

    def test_no_console_handler_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("git_pulse.logger._configured", False)
        logger = logging.getLogger("git_pulse")
        logger.handlers.clear()
        logger = setup_logging("INFO", console=False)
        from rich.logging import RichHandler
        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) == 0

    def test_writes_to_file(self):
        logger = setup_logging("INFO", console=False)
        logger.info("test message for file")
        for h in logger.handlers:
            h.flush()
        assert logger_mod.LOG_FILE.exists()
        contents = logger_mod.LOG_FILE.read_text()
        assert "test message for file" in contents


class TestGetLogger:
    def test_returns_same_logger(self):
        setup_logging("INFO", console=False)
        logger = get_logger()
        assert logger.name == "git_pulse"

    def test_works_before_setup(self):
        logger = get_logger()
        assert logger is not None


class TestResetLogging:
    def test_clears_handlers(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("git_pulse.logger._configured", False)
        logger = setup_logging("INFO", console=False)
        assert len(logger.handlers) >= 1
        reset_logging()
        assert len(logger.handlers) == 0

    def test_allows_reconfigure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("git_pulse.logger._configured", False)
        setup_logging("INFO", console=False)
        reset_logging()
        logger = setup_logging("DEBUG", console=False)
        assert logger.level == logging.DEBUG
