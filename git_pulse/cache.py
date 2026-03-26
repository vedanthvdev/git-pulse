"""Repo cache for git-pulse.

Persists discovered repos and their matching branches to
~/.git-pulse/cache.json so we don't re-scan the filesystem every run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from git_pulse.config import CONFIG_DIR, Config, _atomic_write

CACHE_FILE = CONFIG_DIR / "cache.json"


@dataclass
class CachedRepo:
    path: str
    matching_branches: list[str]

    @property
    def resolved_path(self) -> Path:
        return Path(self.path)


@dataclass
class RepoCache:
    generated_at: str = ""
    config_hash: str = ""
    scan_paths: list[str] = field(default_factory=list)
    branches_to_update: list[str] = field(default_factory=list)
    repos: list[CachedRepo] = field(default_factory=list)

    @property
    def repo_paths(self) -> set[str]:
        return {r.path for r in self.repos}


def load_cache() -> RepoCache | None:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            raw = json.load(f)
        repos = [CachedRepo(**r) for r in raw.get("repos", [])]
        return RepoCache(
            generated_at=raw.get("generated_at", ""),
            config_hash=raw.get("config_hash", ""),
            scan_paths=raw.get("scan_paths", []),
            branches_to_update=raw.get("branches_to_update", []),
            repos=repos,
        )
    except (json.JSONDecodeError, TypeError, KeyError, OSError) as exc:
        logging.getLogger("git_pulse").warning(
            "Cache file corrupt or unreadable (%s), will rebuild: %s",
            CACHE_FILE,
            exc,
        )
        return None


def save_cache(cache: RepoCache) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cache.generated_at = datetime.now(timezone.utc).isoformat()
    data: dict[str, Any] = {
        "generated_at": cache.generated_at,
        "config_hash": cache.config_hash,
        "scan_paths": cache.scan_paths,
        "branches_to_update": cache.branches_to_update,
        "repos": [asdict(r) for r in cache.repos],
    }
    _atomic_write(CACHE_FILE, json.dumps(data, indent=2))


def cache_is_stale(cache: RepoCache, config: Config) -> bool:
    """True when the cache was built with different config settings."""
    return cache.config_hash != config.config_hash


def add_repo_to_cache(cache: RepoCache, repo: CachedRepo) -> None:
    cache.repos.append(repo)


def remove_missing_repos(cache: RepoCache) -> list[str]:
    """Prune repos whose directories no longer exist. Returns removed paths."""
    removed: list[str] = []
    surviving: list[CachedRepo] = []
    for r in cache.repos:
        if r.resolved_path.exists():
            surviving.append(r)
        else:
            removed.append(r.path)
    cache.repos = surviving
    return removed
