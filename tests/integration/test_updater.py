"""Integration tests for the updater engine.

These tests create real git repos with bare remotes, push commits,
and verify the updater correctly pulls, fetches refspecs, handles
dirty repos, and performs the full update cycle.
"""

from __future__ import annotations

from pathlib import Path

from git_pulse.cache import CachedRepo, RepoCache
from git_pulse.config import Config
from git_pulse.updater import run_update
from tests.helpers.git_helpers import create_repo_pair, push_remote_commit


class TestPullOnDefaultBranch:
    def test_pulls_when_on_master(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "pull-master")
        push_remote_commit(remote, "master")

        old_sha = repo.head.commit.hexsha
        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])

        result = run_update(cache, Config(branches_to_update=["master"]))
        assert result.updated == 1
        assert repo.head.commit.hexsha != old_sha

    def test_pulls_when_on_main(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "pull-main", "main")
        push_remote_commit(remote, "main")

        old_sha = repo.head.commit.hexsha
        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["main"])])

        result = run_update(cache, Config(branches_to_update=["main"]))
        assert result.updated == 1
        assert repo.head.commit.hexsha != old_sha


class TestFetchRefspecOnFeatureBranch:
    def test_updates_master_while_on_feature(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "fetch-refspec")
        repo.git.checkout("-b", "feature/test")
        push_remote_commit(remote, "master")

        old_master = repo.refs["master"].commit.hexsha
        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])

        result = run_update(cache, Config(branches_to_update=["master"]))
        assert result.updated == 1
        assert repo.refs["master"].commit.hexsha != old_master
        assert repo.active_branch.name == "feature/test"

    def test_working_directory_untouched(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "wd-untouched")
        repo.git.checkout("-b", "feature/x")
        (local / "local_work.txt").write_text("in progress")
        repo.index.add(["local_work.txt"])
        repo.index.commit("Work in progress")

        push_remote_commit(remote, "master")
        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])

        result = run_update(cache, Config(branches_to_update=["master"]))
        assert result.updated == 1
        assert (local / "local_work.txt").read_text() == "in progress"
        assert repo.active_branch.name == "feature/x"


class TestMultiBranchUpdate:
    def test_updates_both_master_and_main(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "multi")
        repo.git.checkout("-b", "main")
        repo.git.push("origin", "main")
        repo.git.checkout("-b", "feature/multi")

        push_remote_commit(remote, "master")
        old_master = repo.refs["master"].commit.hexsha

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master", "main"])])
        result = run_update(cache, Config(branches_to_update=["master", "main"]))

        assert result.updated == 1
        assert "master" in result.results[0].branches_updated
        assert "main" in result.results[0].branches_updated
        assert repo.refs["master"].commit.hexsha != old_master
        assert repo.active_branch.name == "feature/multi"

    def test_pulls_current_fetches_other(self, tmp_path: Path):
        """When on main, main gets pull, master gets fetch refspec."""
        remote, local, repo = create_repo_pair(tmp_path, "mixed")
        repo.git.checkout("-b", "main")
        repo.git.push("origin", "main")

        push_remote_commit(remote, "master")
        old_master = repo.refs["master"].commit.hexsha

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master", "main"])])
        result = run_update(cache, Config(branches_to_update=["master", "main"]))

        assert result.updated == 1
        assert repo.refs["master"].commit.hexsha != old_master
        assert repo.active_branch.name == "main"


class TestSafetyGuardrails:
    def test_stashes_and_updates_dirty_repo_untracked(self, tmp_path: Path):
        remote, local, _ = create_repo_pair(tmp_path, "dirty-untracked")
        (local / "untracked.txt").write_text("dirty")
        push_remote_commit(remote, "master")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.updated == 1
        assert (local / "untracked.txt").read_text() == "dirty"

    def test_stashes_and_updates_dirty_repo_staged(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "dirty-staged")
        (local / "staged.txt").write_text("staged")
        repo.index.add(["staged.txt"])
        push_remote_commit(remote, "master")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.updated == 1
        assert (local / "staged.txt").exists()

    def test_stashes_and_updates_dirty_repo_modified(self, tmp_path: Path):
        remote, local, _ = create_repo_pair(tmp_path, "dirty-modified")
        (local / "README.md").write_text("changed")
        push_remote_commit(remote, "master")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.updated == 1
        assert (local / "README.md").read_text() == "changed"

    def test_skips_detached_head(self, tmp_path: Path):
        _, local, repo = create_repo_pair(tmp_path, "detached")
        sha = repo.head.commit.hexsha
        repo.git.checkout(sha)

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.skipped == 1
        assert result.results[0].message == "Detached HEAD"

    def test_skips_mid_rebase(self, tmp_path: Path):
        _, local, repo = create_repo_pair(tmp_path, "mid-rebase")
        (Path(repo.git_dir) / "rebase-merge").mkdir()

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.skipped == 1
        assert result.results[0].message == "Mid-rebase or merge"

    def test_skips_mid_merge(self, tmp_path: Path):
        _, local, repo = create_repo_pair(tmp_path, "mid-merge")
        (Path(repo.git_dir) / "MERGE_HEAD").write_text("fake")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.skipped == 1

    def test_handles_invalid_repo_path(self, tmp_path: Path, monkeypatch):
        fake = tmp_path / "not-a-repo"
        fake.mkdir()

        monkeypatch.setattr(
            "git_pulse.updater.probe_connectivity",
            lambda path: True,
        )

        cache = RepoCache(repos=[CachedRepo(path=str(fake), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.errors == 1
        assert "Invalid" in result.results[0].message


class TestDryRun:
    def test_no_changes_on_pull(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "dry-pull")
        push_remote_commit(remote, "master")
        old_sha = repo.head.commit.hexsha

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]), dry_run=True)

        assert result.updated == 1
        assert repo.head.commit.hexsha == old_sha

    def test_no_changes_on_fetch(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "dry-fetch")
        repo.git.checkout("-b", "feature/dry")
        push_remote_commit(remote, "master")
        old_master = repo.refs["master"].commit.hexsha

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]), dry_run=True)

        assert result.updated == 1
        assert repo.refs["master"].commit.hexsha == old_master


class TestConnectivityFailFast:
    def test_aborts_on_unreachable_remote(self, tmp_path: Path, monkeypatch):
        """When connectivity probe fails, no repos should be processed."""
        _, local, _ = create_repo_pair(tmp_path, "unreachable")

        monkeypatch.setattr(
            "git_pulse.updater.probe_connectivity",
            lambda path: False,
        )

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.aborted is True
        assert "Network unreachable" in result.abort_reason
        assert result.results == []

    def test_empty_cache_no_abort(self):
        cache = RepoCache(repos=[])
        result = run_update(cache, Config(branches_to_update=["master"]))
        assert result.aborted is False
        assert result.total == 0


class TestFastForwardRebase:
    def test_rebases_feature_branch_when_enabled(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "ff-rebase")
        repo.git.checkout("-b", "feature/rebase")
        (local / "feature.txt").write_text("feature work")
        repo.index.add(["feature.txt"])
        repo.index.commit("Feature commit")

        push_remote_commit(remote, "master", filename="upstream.txt")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        config = Config(branches_to_update=["master"], fast_forward_rebase=True)

        result = run_update(cache, config)
        assert result.updated == 1
        assert repo.active_branch.name == "feature/rebase"
        assert (local / "upstream.txt").exists()

    def test_no_rebase_when_disabled(self, tmp_path: Path):
        remote, local, repo = create_repo_pair(tmp_path, "no-ff-rebase")
        repo.git.checkout("-b", "feature/norebase")

        push_remote_commit(remote, "master", filename="upstream.txt")

        cache = RepoCache(repos=[CachedRepo(path=str(local), matching_branches=["master"])])
        config = Config(branches_to_update=["master"], fast_forward_rebase=False)

        result = run_update(cache, config)
        assert result.updated == 1
        assert not (local / "upstream.txt").exists()


class TestMultiRepoRun:
    def test_processes_all_repos(self, tmp_path: Path):
        repos_data = []
        for name in ["a", "b", "c"]:
            remote, local, _repo = create_repo_pair(tmp_path, name)
            push_remote_commit(remote, "master")
            repos_data.append(CachedRepo(path=str(local), matching_branches=["master"]))

        cache = RepoCache(repos=repos_data)
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.total == 3
        assert result.updated == 3
        assert result.skipped == 0
        assert result.errors == 0

    def test_mixed_results(self, tmp_path: Path):
        remote_ok, local_ok, _ = create_repo_pair(tmp_path, "ok")
        push_remote_commit(remote_ok, "master")

        remote_dirty, local_dirty, _ = create_repo_pair(tmp_path, "dirty")
        (local_dirty / "dirt.txt").write_text("dirty")
        push_remote_commit(remote_dirty, "master")

        cache = RepoCache(
            repos=[
                CachedRepo(path=str(local_ok), matching_branches=["master"]),
                CachedRepo(path=str(local_dirty), matching_branches=["master"]),
            ]
        )
        result = run_update(cache, Config(branches_to_update=["master"]))

        assert result.total == 2
        assert result.updated == 2
        assert (local_dirty / "dirt.txt").read_text() == "dirty"
