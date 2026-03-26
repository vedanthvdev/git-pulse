"""Unit tests for updater helper functions.

Tests the safety-check helpers (_is_repo_dirty, _is_mid_rebase_or_merge,
_get_current_branch) and the dataclasses (RepoResult, RunResult).
Uses real git repos on disk to exercise actual git state detection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from git_pulse.updater import (
    RepoResult,
    RepoStatus,
    RunResult,
    _get_current_branch,
    _is_mid_rebase_or_merge,
    _is_repo_dirty,
    _validate_repo,
    _update_branch,
)
from git_pulse.cache import CachedRepo
from tests.helpers.git_helpers import make_bare_remote, make_local_repo, push_remote_commit


class TestIsRepoDirty:
    def test_clean_repo(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        assert _is_repo_dirty(repo) is False

    def test_untracked_file(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        (local / "untracked.txt").write_text("hello")
        repo = Repo(str(local))
        assert _is_repo_dirty(repo) is True

    def test_modified_file(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        (local / "README.md").write_text("modified content")
        repo = Repo(str(local))
        assert _is_repo_dirty(repo) is True

    def test_staged_file(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        (local / "staged.txt").write_text("staged")
        repo = Repo(str(local))
        repo.index.add(["staged.txt"])
        assert _is_repo_dirty(repo) is True


class TestIsMidRebaseOrMerge:
    def test_normal_repo(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        assert _is_mid_rebase_or_merge(repo) is False

    def test_fake_rebase_merge_dir(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        (Path(repo.git_dir) / "rebase-merge").mkdir()
        assert _is_mid_rebase_or_merge(repo) is True

    def test_fake_rebase_apply_dir(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        (Path(repo.git_dir) / "rebase-apply").mkdir()
        assert _is_mid_rebase_or_merge(repo) is True

    def test_fake_merge_head(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        (Path(repo.git_dir) / "MERGE_HEAD").write_text("fake")
        assert _is_mid_rebase_or_merge(repo) is True


class TestGetCurrentBranch:
    def test_on_named_branch(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        assert _get_current_branch(repo) == "master"

    def test_on_feature_branch(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        repo.git.checkout("-b", "feature/xyz")
        assert _get_current_branch(repo) == "feature/xyz"

    def test_detached_head_returns_none(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        sha = repo.head.commit.hexsha
        repo.git.checkout(sha)
        assert _get_current_branch(repo) is None


class TestDataclasses:
    def test_repo_result_defaults(self):
        r = RepoResult(path="/a", status=RepoStatus.UPDATED)
        assert r.branches_updated == []
        assert r.branches_failed == []
        assert r.message == ""

    def test_repo_status_enum_values(self):
        assert RepoStatus.UPDATED == "updated"
        assert RepoStatus.SKIPPED == "skipped"
        assert RepoStatus.ERROR == "error"

    def test_repo_status_is_str_compatible(self):
        assert RepoStatus.UPDATED == "updated"
        assert isinstance(RepoStatus.UPDATED, str)

    def test_run_result_defaults(self):
        r = RunResult()
        assert r.total == 0
        assert r.updated == 0
        assert r.skipped == 0
        assert r.errors == 0
        assert r.aborted is False
        assert r.results == []


class TestValidateRepo:
    def test_returns_error_for_invalid_path(self, tmp_path: Path):
        fake = tmp_path / "not-a-repo"
        fake.mkdir()
        cached = CachedRepo(path=str(fake), matching_branches=["master"])
        _, _, result = _validate_repo(cached)
        assert result is not None
        assert result.status == RepoStatus.ERROR

    def test_returns_skip_for_detached_head(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        repo.git.checkout(repo.head.commit.hexsha)

        cached = CachedRepo(path=str(local), matching_branches=["master"])
        _, _, result = _validate_repo(cached)
        assert result is not None
        assert result.status == RepoStatus.SKIPPED
        assert "Detached HEAD" in result.message

    def test_returns_skip_for_dirty_repo(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        (local / "untracked.txt").write_text("dirty")

        cached = CachedRepo(path=str(local), matching_branches=["master"])
        _, _, result = _validate_repo(cached)
        assert result is not None
        assert result.status == RepoStatus.SKIPPED

    def test_returns_none_for_valid_repo(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)

        cached = CachedRepo(path=str(local), matching_branches=["master"])
        repo, current, result = _validate_repo(cached)
        assert result is None
        assert current == "master"


class TestUpdateBranch:
    def test_pull_on_current_branch(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        push_remote_commit(remote, "master")

        repo = Repo(str(local))
        old_sha = repo.head.commit.hexsha
        assert _update_branch(repo, "master", "master", dry_run=False) is True
        assert repo.head.commit.hexsha != old_sha

    def test_fetch_refspec_on_other_branch(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        repo = Repo(str(local))
        repo.git.checkout("-b", "feature/x")
        push_remote_commit(remote, "master")

        old_master = repo.refs["master"].commit.hexsha
        assert _update_branch(repo, "master", "feature/x", dry_run=False) is True
        assert repo.refs["master"].commit.hexsha != old_master

    def test_dry_run_no_change(self, tmp_path: Path):
        remote = tmp_path / "r.git"
        local = tmp_path / "l"
        make_bare_remote(remote)
        make_local_repo(local, remote)
        push_remote_commit(remote, "master")

        repo = Repo(str(local))
        old_sha = repo.head.commit.hexsha
        assert _update_branch(repo, "master", "master", dry_run=True) is True
        assert repo.head.commit.hexsha == old_sha
