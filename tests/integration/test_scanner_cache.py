"""Integration tests for the scanner + cache lifecycle.

These tests exercise the full flow: scanning directories, building the cache,
detecting new/removed repos, and rebuilding on config changes. All use real
git repos on disk.
"""

from __future__ import annotations

from pathlib import Path

from git_pulse.cache import load_cache
from git_pulse.config import Config
from git_pulse.scanner import full_scan, get_or_build_cache
from tests.helpers.git_helpers import create_repo_pair, make_bare_remote, make_local_repo


class TestFullScan:
    def test_discovers_single_repo(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        _, _local, _ = create_repo_pair(tmp_path, "alpha")
        config = Config(scan_paths=[str(tmp_path / "repos")], branches_to_update=["master"])
        cache = full_scan(config)

        assert len(cache.repos) == 1
        assert cache.repos[0].matching_branches == ["master"]

    def test_discovers_multiple_repos(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        for name in ["repo-a", "repo-b", "repo-c"]:
            create_repo_pair(tmp_path, name)

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = full_scan(config)
        assert len(cache.repos) == 3

    def test_discovers_repos_with_different_branches(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()

        create_repo_pair(tmp_path, "repo-master", "master")
        create_repo_pair(tmp_path, "repo-main", "main")
        create_repo_pair(tmp_path, "repo-develop", "develop")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master", "main"])
        cache = full_scan(config)

        assert len(cache.repos) == 2
        names = {Path(r.path).name for r in cache.repos}
        assert names == {"repo-master", "repo-main"}

    def test_repo_with_both_branches(self, tmp_path: Path):
        """A repo that has both master and main should report both."""
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        _remote, _local, repo = create_repo_pair(tmp_path, "dual")
        repo.git.checkout("-b", "main")
        repo.git.push("origin", "main")
        repo.git.checkout("master")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master", "main"])
        cache = full_scan(config)

        assert len(cache.repos) == 1
        assert sorted(cache.repos[0].matching_branches) == ["main", "master"]

    def test_skips_repos_without_matching_branches(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "develop-only", "develop")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master", "main"])
        cache = full_scan(config)
        assert len(cache.repos) == 0

    def test_respects_exclude_paths(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        _, local, _ = create_repo_pair(tmp_path, "excluded")

        config = Config(
            scan_paths=[str(scan_dir)],
            branches_to_update=["master"],
            exclude_paths=[str(local)],
        )
        cache = full_scan(config)
        assert len(cache.repos) == 0

    def test_handles_nonexistent_scan_path(self, tmp_path: Path):
        config = Config(
            scan_paths=[str(tmp_path / "does_not_exist")],
            branches_to_update=["master"],
        )
        cache = full_scan(config)
        assert len(cache.repos) == 0

    def test_scan_depth_limits_discovery(self, tmp_path: Path):
        """Repos nested deeper than scan_depth should not be found."""
        scan_dir = tmp_path / "repos"
        deep = scan_dir / "a" / "b" / "c" / "deep-repo"
        remote = tmp_path / "remotes" / "deep.git"
        make_bare_remote(remote)
        make_local_repo(deep, remote)

        config = Config(scan_paths=[str(scan_dir)], scan_depth=2, branches_to_update=["master"])
        cache = full_scan(config)
        assert len(cache.repos) == 0

        config_deep = Config(
            scan_paths=[str(scan_dir)], scan_depth=5, branches_to_update=["master"]
        )
        cache_deep = full_scan(config_deep)
        assert len(cache_deep.repos) == 1

    def test_persists_cache_to_disk(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "persisted")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        full_scan(config)

        loaded = load_cache()
        assert loaded is not None
        assert len(loaded.repos) == 1

    def test_stores_config_hash(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "hashed")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = full_scan(config)
        assert cache.config_hash == config.config_hash


class TestGetOrBuildCache:
    def test_builds_on_first_call(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "first")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = get_or_build_cache(config)
        assert len(cache.repos) == 1

    def test_returns_cached_on_second_call(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "cached")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        get_or_build_cache(config)
        cache2 = get_or_build_cache(config)
        assert len(cache2.repos) == 1

    def test_detects_new_repos(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "repo1")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = get_or_build_cache(config)
        assert len(cache.repos) == 1

        create_repo_pair(tmp_path, "repo2")
        cache = get_or_build_cache(config)
        assert len(cache.repos) == 2

    def test_prunes_removed_repos(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        _, local, _ = create_repo_pair(tmp_path, "ephemeral")

        config = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = get_or_build_cache(config)
        assert len(cache.repos) == 1

        import shutil

        shutil.rmtree(local)

        cache = get_or_build_cache(config)
        assert len(cache.repos) == 0

    def test_rebuilds_on_config_change(self, tmp_path: Path):
        scan_dir = tmp_path / "repos"
        scan_dir.mkdir()
        create_repo_pair(tmp_path, "configchange")

        config_v1 = Config(scan_paths=[str(scan_dir)], branches_to_update=["master"])
        cache = get_or_build_cache(config_v1)
        assert len(cache.repos) == 1

        config_v2 = Config(scan_paths=[str(scan_dir)], branches_to_update=["develop"])
        cache = get_or_build_cache(config_v2)
        assert len(cache.repos) == 0

    def test_multiple_scan_paths(self, tmp_path: Path):
        dir_a = tmp_path / "repos_a"
        dir_b = tmp_path / "repos_b"
        dir_a.mkdir()
        dir_b.mkdir()

        remote_a = tmp_path / "remotes" / "a.git"
        make_bare_remote(remote_a)
        make_local_repo(dir_a / "a", remote_a)

        remote_b = tmp_path / "remotes" / "b.git"
        make_bare_remote(remote_b)
        make_local_repo(dir_b / "b", remote_b)

        config = Config(scan_paths=[str(dir_a), str(dir_b)], branches_to_update=["master"])
        cache = get_or_build_cache(config)
        assert len(cache.repos) == 2
