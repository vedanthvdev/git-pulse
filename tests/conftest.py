"""Root conftest — fixtures available to all test levels.

Provides the isolation fixture that redirects ~/.git-pulse to a temp
directory so tests never touch the real user config, cache, or logs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from git_pulse.logger import setup_logging


@pytest.fixture(autouse=True)
def isolate_git_pulse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all git-pulse state dirs to a temp path.

    Every test automatically gets this — no test can leak into the real
    ~/.git-pulse directory.
    """
    fake_dir = tmp_path / ".git-pulse"
    fake_dir.mkdir()

    monkeypatch.setattr("git_pulse.config.CONFIG_DIR", fake_dir)
    monkeypatch.setattr("git_pulse.config.CONFIG_FILE", fake_dir / "config.yml")
    monkeypatch.setattr("git_pulse.cache.CONFIG_DIR", fake_dir)
    monkeypatch.setattr("git_pulse.cache.CACHE_FILE", fake_dir / "cache.json")
    monkeypatch.setattr("git_pulse.logger.LOG_DIR", fake_dir / "logs")
    monkeypatch.setattr("git_pulse.logger.LOG_FILE", fake_dir / "logs" / "test.log")
    monkeypatch.setattr("git_pulse.logger._configured", False)

    setup_logging("DEBUG", console=False)
