"""Repo scanner for git-pulse.

Walks configured scan_paths to discover git repositories, determines which
of the user's branches_to_update exist in each, and maintains the cache.
"""

from __future__ import annotations

import os
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

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
from git_pulse.logger import get_logger


def _is_excluded(path: Path, exclude_paths: list[Path]) -> bool:
    for ep in exclude_paths:
        try:
            path.relative_to(ep)
            return True
        except ValueError:
            continue
    return False


def _find_git_repos(
    root: Path,
    max_depth: int,
    exclude_paths: list[Path],
    _current_depth: int = 0,
) -> list[Path]:
    """Recursively find directories containing a .git folder."""
    repos: list[Path] = []

    if _current_depth > max_depth:
        return repos

    if _is_excluded(root, exclude_paths):
        return repos

    try:
        entries = sorted(root.iterdir())
    except PermissionError:
        return repos

    if (root / ".git").is_dir():
        repos.append(root)
        return repos

    for entry in entries:
        if entry.is_dir() and not entry.name.startswith("."):
            repos.extend(
                _find_git_repos(entry, max_depth, exclude_paths, _current_depth + 1)
            )

    return repos


def _matching_branches(repo_path: Path, branches: list[str]) -> list[str]:
    """Return which of the requested branch names exist as local branches."""
    try:
        repo = Repo(str(repo_path))
    except InvalidGitRepositoryError:
        return []

    local_branch_names = {ref.name for ref in repo.branches}  # type: ignore[union-attr]
    return [b for b in branches if b in local_branch_names]


def full_scan(config: Config) -> RepoCache:
    """Walk all scan paths and build a fresh cache from scratch."""
    log = get_logger()
    log.info("Starting full scan of %d path(s)", len(config.scan_paths))

    exclude = config.resolved_exclude_paths
    all_repos: list[CachedRepo] = []

    for scan_path in config.resolved_scan_paths:
        if not scan_path.is_dir():
            log.warning("Scan path does not exist: %s", scan_path)
            continue

        discovered = _find_git_repos(scan_path, config.scan_depth, exclude)
        for repo_path in discovered:
            matched = _matching_branches(repo_path, config.branches_to_update)
            if matched:
                all_repos.append(
                    CachedRepo(path=str(repo_path), matching_branches=matched)
                )
                log.debug(
                    "  %s -> branches: %s", repo_path.name, ", ".join(matched)
                )
            else:
                log.debug("  %s -> no matching branches, skipping", repo_path.name)

    cache = RepoCache(
        config_hash=config.config_hash,
        scan_paths=config.scan_paths,
        branches_to_update=config.branches_to_update,
        repos=all_repos,
    )
    save_cache(cache)
    log.info("Scan complete: %d repo(s) cached", len(all_repos))
    return cache


def _quick_discover_new_repos(cache: RepoCache, config: Config) -> list[CachedRepo]:
    """Fast check for new repos not yet in the cache.

    Walks each scan_path's subdirectories (up to scan_depth) using
    os.scandir — only stat calls, no git operations until a new .git
    directory is found.
    """
    log = get_logger()
    known_paths = cache.repo_paths
    exclude = config.resolved_exclude_paths
    new_repos: list[CachedRepo] = []

    for scan_path in config.resolved_scan_paths:
        if not scan_path.is_dir():
            continue
        candidates = _find_git_repos(scan_path, config.scan_depth, exclude)
        for repo_path in candidates:
            if str(repo_path) not in known_paths:
                matched = _matching_branches(repo_path, config.branches_to_update)
                if matched:
                    new_repos.append(
                        CachedRepo(path=str(repo_path), matching_branches=matched)
                    )
                    log.info("New repo discovered: %s (%s)", repo_path.name, ", ".join(matched))

    return new_repos


def get_or_build_cache(config: Config) -> RepoCache:
    """Load the cache, refresh incrementally, or rebuild if stale.

    1. If no cache exists -> full scan.
    2. If config changed (hash mismatch) -> full scan.
    3. Otherwise -> prune removed repos, discover new ones, save.
    """
    log = get_logger()
    cache = load_cache()

    if cache is None:
        log.info("No cache found, performing full scan")
        return full_scan(config)

    if cache_is_stale(cache, config):
        log.info("Config changed since last scan, rebuilding cache")
        return full_scan(config)

    removed = remove_missing_repos(cache)
    if removed:
        log.info("Pruned %d removed repo(s) from cache", len(removed))

    new_repos = _quick_discover_new_repos(cache, config)
    for repo in new_repos:
        add_repo_to_cache(cache, repo)

    if removed or new_repos:
        cache.config_hash = config.config_hash
        save_cache(cache)

    return cache
