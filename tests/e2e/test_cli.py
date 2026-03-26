"""End-to-end tests for the git-pulse CLI.

These tests invoke CLI commands via Typer's CliRunner and verify the full
pipeline: config creation, scanning, updating, and output formatting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_pulse.cli import app
from git_pulse.config import Config, save_config
from git_pulse.scanner import full_scan
from tests.helpers.git_helpers import create_repo_pair, push_remote_commit

runner = CliRunner()


@pytest.fixture()
def configured_env(tmp_path: Path):
    """Set up a scan directory with repos and save a valid config."""
    scan_dir = tmp_path / "repos"
    scan_dir.mkdir()

    create_repo_pair(tmp_path, "service-a")
    create_repo_pair(tmp_path, "service-b")

    config = Config(
        scan_paths=[str(scan_dir)],
        branches_to_update=["master"],
        interval_minutes=60,
    )
    save_config(config)
    full_scan(config)
    return tmp_path


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_short_version_flag(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestHelp:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # Typer with no_args_is_help=True exits with code 0 on some versions, 2 on others
        assert result.exit_code in (0, 2)
        assert "git-pulse" in result.output.lower()

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "run" in result.output
        assert "sync" in result.output
        assert "scan" in result.output
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        assert "logs" in result.output
        assert "config" in result.output
        assert "list" in result.output

    def test_run_help(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output


class TestScanCommand:
    def test_scan_discovers_repos(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "scan-test")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        save_config(config)

        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0
        assert "1 repo(s) found" in result.output

    def test_scan_with_no_repos(self, tmp_path: Path):
        scan_dir = tmp_path / "empty"
        scan_dir.mkdir()

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        save_config(config)

        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0
        assert "0 repo(s) found" in result.output


class TestListCommand:
    def test_list_shows_repos(self, configured_env):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "service-a" in result.output
        assert "service-b" in result.output
        assert "master" in result.output

    def test_list_shows_count(self, configured_env):
        result = runner.invoke(app, ["list"])
        assert "2" in result.output

    def test_list_with_empty_cache(self, tmp_path: Path):
        scan_dir = tmp_path / "empty"
        scan_dir.mkdir()
        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        save_config(config)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0


class TestConfigCommand:
    def test_print_all_config(self, configured_env):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "interval_minutes" in result.output
        assert "branches_to_update" in result.output
        assert "scan_paths" in result.output

    def test_get_single_value(self, configured_env):
        result = runner.invoke(app, ["config", "interval_minutes"])
        assert result.exit_code == 0
        assert "60" in result.output

    def test_set_value(self, configured_env):
        result = runner.invoke(app, ["config", "interval_minutes", "30"])
        assert result.exit_code == 0
        assert "30" in result.output

    def test_get_unknown_key(self, configured_env):
        result = runner.invoke(app, ["config", "nonexistent"])
        assert result.exit_code == 1

    def test_set_unknown_key(self, configured_env):
        result = runner.invoke(app, ["config", "nonexistent", "value"])
        assert result.exit_code == 1


class TestRunCommand:
    def test_run_updates_repos(self, configured_env: Path):
        remote_a = configured_env / "remotes" / "service-a.git"
        push_remote_commit(remote_a, "master")

        result = runner.invoke(app, ["run"])
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_run_dry_run(self, configured_env: Path):
        remote_a = configured_env / "remotes" / "service-a.git"
        push_remote_commit(remote_a, "master")

        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code == 0

    def test_run_with_connectivity_failure(self, configured_env, monkeypatch):
        monkeypatch.setattr(
            "git_pulse.updater.probe_connectivity",
            lambda path: False,
        )
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "aborted" in result.output.lower()


class TestSyncCommand:
    def test_sync_is_alias_for_run(self, configured_env):
        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0


class TestStatusCommand:
    def test_status_shows_info(self, configured_env):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Version" in result.output
        assert "0.1.0" in result.output
        assert "Interval" in result.output
        assert "Cached repos" in result.output

    def test_status_without_config(self):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
