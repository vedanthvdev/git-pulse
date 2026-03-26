"""Unit tests for the cache module.

Tests JSON serialization, staleness detection, repo pruning, and edge cases.
No git repos needed — operates on cache data structures and temp files.
"""

from __future__ import annotations

import json
from pathlib import Path

import git_pulse.cache as cache_mod
from git_pulse.cache import (
    CachedRepo,
    RepoCache,
    add_repo_to_cache,
    cache_is_stale,
    load_cache,
    remove_missing_repos,
    save_cache,
)
from git_pulse.config import Config


class TestCachedRepo:
    def test_resolved_path(self):
        repo = CachedRepo(path="/Users/test/repo", matching_branches=["master"])
        assert repo.resolved_path == Path("/Users/test/repo")

    def test_matching_branches_preserved(self):
        repo = CachedRepo(path="/a", matching_branches=["master", "main"])
        assert repo.matching_branches == ["master", "main"]


class TestRepoCache:
    def test_repo_paths_property(self):
        cache = RepoCache(
            repos=[
                CachedRepo(path="/a", matching_branches=["master"]),
                CachedRepo(path="/b", matching_branches=["main"]),
                CachedRepo(path="/c", matching_branches=["master", "main"]),
            ]
        )
        assert cache.repo_paths == {"/a", "/b", "/c"}

    def test_repo_paths_empty(self):
        cache = RepoCache()
        assert cache.repo_paths == set()

    def test_default_fields(self):
        cache = RepoCache()
        assert cache.generated_at == ""
        assert cache.config_hash == ""
        assert cache.scan_paths == []
        assert cache.branches_to_update == []
        assert cache.repos == []


class TestSaveAndLoad:
    def test_round_trip(self):
        original = RepoCache(
            config_hash="abc123",
            scan_paths=["~/Code"],
            branches_to_update=["master", "main"],
            repos=[
                CachedRepo(path="/tmp/repo-a", matching_branches=["master"]),
                CachedRepo(path="/tmp/repo-b", matching_branches=["master", "main"]),
            ],
        )
        save_cache(original)
        loaded = load_cache()

        assert loaded is not None
        assert loaded.config_hash == "abc123"
        assert loaded.scan_paths == ["~/Code"]
        assert loaded.branches_to_update == ["master", "main"]
        assert len(loaded.repos) == 2
        assert loaded.repos[0].path == "/tmp/repo-a"
        assert loaded.repos[0].matching_branches == ["master"]
        assert loaded.repos[1].matching_branches == ["master", "main"]

    def test_generated_at_is_set_on_save(self):
        cache = RepoCache(repos=[])
        assert cache.generated_at == ""
        save_cache(cache)
        loaded = load_cache()
        assert loaded is not None
        assert loaded.generated_at != ""

    def test_load_missing_file_returns_none(self):
        assert load_cache() is None

    def test_load_corrupt_json_returns_none(self):
        cf = cache_mod.CACHE_FILE
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text("{invalid json!!")
        assert load_cache() is None

    def test_load_empty_file_returns_none(self):
        cf = cache_mod.CACHE_FILE
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text("")
        assert load_cache() is None

    def test_save_creates_directory(self, tmp_path: Path):
        cache = RepoCache()
        save_cache(cache)
        assert cache_mod.CACHE_FILE.exists()

    def test_json_structure(self):
        cache = RepoCache(
            config_hash="xyz",
            scan_paths=["~/a"],
            branches_to_update=["master"],
            repos=[CachedRepo(path="/r", matching_branches=["master"])],
        )
        save_cache(cache)
        raw = json.loads(cache_mod.CACHE_FILE.read_text())

        assert "generated_at" in raw
        assert raw["config_hash"] == "xyz"
        assert raw["scan_paths"] == ["~/a"]
        assert raw["branches_to_update"] == ["master"]
        assert len(raw["repos"]) == 1
        assert raw["repos"][0]["path"] == "/r"


class TestCacheStaleness:
    def test_stale_when_hash_differs(self):
        cache = RepoCache(config_hash="old")
        config = Config(scan_paths=["~/a"], branches_to_update=["master"])
        assert cache_is_stale(cache, config) is True

    def test_fresh_when_hash_matches(self):
        config = Config(scan_paths=["~/a"], branches_to_update=["master"])
        cache = RepoCache(config_hash=config.config_hash)
        assert cache_is_stale(cache, config) is False


class TestAddRepoToCache:
    def test_appends_to_existing(self):
        cache = RepoCache(repos=[CachedRepo(path="/a", matching_branches=["master"])])
        new = CachedRepo(path="/b", matching_branches=["main"])
        add_repo_to_cache(cache, new)

        assert len(cache.repos) == 2
        assert cache.repos[1].path == "/b"

    def test_add_to_empty(self):
        cache = RepoCache()
        add_repo_to_cache(cache, CachedRepo(path="/x", matching_branches=["master"]))
        assert len(cache.repos) == 1


class TestRemoveMissingRepos:
    def test_prunes_nonexistent_paths(self, tmp_path: Path):
        existing = tmp_path / "exists"
        existing.mkdir()

        cache = RepoCache(
            repos=[
                CachedRepo(path=str(existing), matching_branches=["master"]),
                CachedRepo(path="/nonexistent/repo", matching_branches=["main"]),
            ]
        )

        removed = remove_missing_repos(cache)
        assert removed == ["/nonexistent/repo"]
        assert len(cache.repos) == 1
        assert cache.repos[0].path == str(existing)

    def test_nothing_to_prune(self, tmp_path: Path):
        d = tmp_path / "repo"
        d.mkdir()
        cache = RepoCache(repos=[CachedRepo(path=str(d), matching_branches=["master"])])
        removed = remove_missing_repos(cache)
        assert removed == []
        assert len(cache.repos) == 1

    def test_all_removed(self):
        cache = RepoCache(
            repos=[
                CachedRepo(path="/gone1", matching_branches=["master"]),
                CachedRepo(path="/gone2", matching_branches=["main"]),
            ]
        )
        removed = remove_missing_repos(cache)
        assert len(removed) == 2
        assert cache.repos == []
