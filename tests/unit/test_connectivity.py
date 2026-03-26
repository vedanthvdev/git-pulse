"""Unit tests for the connectivity probe.

Tests with local file:// remotes (always reachable) and invalid paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from git import GitCommandError

from git_pulse.connectivity import probe_connectivity
from tests.helpers.git_helpers import make_bare_remote, make_local_repo


class TestProbeConnectivity:
    def test_succeeds_with_local_remote(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        assert probe_connectivity(str(local)) is True

    def test_fails_with_invalid_path(self, tmp_path: Path):
        fake = tmp_path / "not-a-repo"
        fake.mkdir()
        assert probe_connectivity(str(fake)) is False

    def test_fails_with_nonexistent_path(self):
        assert probe_connectivity("/nonexistent/path") is False

    @patch("git_pulse.connectivity.Repo")
    def test_handles_git_command_error(self, mock_repo_cls):
        mock_repo = MagicMock()
        mock_repo.git.ls_remote.side_effect = GitCommandError("ls-remote", 128, stderr="fatal: no remote")
        mock_repo_cls.return_value = mock_repo

        assert probe_connectivity("/fake") is False

    @patch("git_pulse.connectivity.Repo")
    def test_handles_unexpected_exception(self, mock_repo_cls):
        mock_repo_cls.side_effect = RuntimeError("unexpected")
        assert probe_connectivity("/fake") is False
