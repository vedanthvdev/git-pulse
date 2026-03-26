"""Core update engine for git-pulse.

Iterates cached repos, detects the user's current branch, and updates
each matching branch — either via pull (if the user is on it) or via
a refspec fetch (if the user is on a different branch).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo

from git_pulse.cache import CachedRepo, RepoCache
from git_pulse.config import Config
from git_pulse.connectivity import probe_connectivity
from git_pulse.logger import get_logger


class RepoStatus(str, Enum):
    """Possible outcomes for a single repo update. str mixin keeps JSON-friendly."""
    UPDATED = "updated"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class RepoResult:
    path: str
    status: RepoStatus
    branches_updated: list[str] = field(default_factory=list)
    branches_failed: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class RunResult:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    aborted: bool = False
    abort_reason: str = ""
    results: list[RepoResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def _is_repo_dirty(repo: Repo) -> bool:
    return repo.is_dirty(untracked_files=True)


def _is_mid_rebase_or_merge(repo: Repo) -> bool:
    git_dir = Path(repo.git_dir)
    indicators = [
        git_dir / "rebase-merge",
        git_dir / "rebase-apply",
        git_dir / "MERGE_HEAD",
    ]
    return any(p.exists() for p in indicators)


def _get_current_branch(repo: Repo) -> str | None:
    """Return the current branch name, or None for detached HEAD."""
    try:
        return repo.active_branch.name
    except TypeError:
        return None


# ---------------------------------------------------------------------------
# Validate repo state before update
# ---------------------------------------------------------------------------

def _validate_repo(cached: CachedRepo) -> tuple[Repo, str, RepoResult | None]:
    """Open the repo, check preconditions.

    Returns (repo, current_branch, None) on success,
    or (_, _, RepoResult) with the skip/error reason on failure.
    """
    log = get_logger()
    name = Path(cached.path).name

    try:
        repo = Repo(cached.path)
    except InvalidGitRepositoryError:
        return Repo.__new__(Repo), "", RepoResult(
            path=cached.path, status=RepoStatus.ERROR, message="Invalid git repo",
        )

    current = _get_current_branch(repo)
    if current is None:
        log.info("  %s: detached HEAD, skipping", name)
        return repo, "", RepoResult(
            path=cached.path, status=RepoStatus.SKIPPED, message="Detached HEAD",
        )

    if _is_repo_dirty(repo):
        log.info("  %s: dirty working tree, skipping", name)
        return repo, current, RepoResult(
            path=cached.path, status=RepoStatus.SKIPPED, message="Dirty working tree",
        )

    if _is_mid_rebase_or_merge(repo):
        log.info("  %s: mid-rebase/merge, skipping", name)
        return repo, current, RepoResult(
            path=cached.path, status=RepoStatus.SKIPPED, message="Mid-rebase or merge",
        )

    return repo, current, None


# ---------------------------------------------------------------------------
# Branch update operations
# ---------------------------------------------------------------------------

def _update_branch(
    repo: Repo,
    branch: str,
    current: str,
    dry_run: bool,
) -> bool:
    """Update a single branch. Returns True on success, False on git failure."""
    log = get_logger()
    name = Path(repo.working_dir).name

    if branch == current:
        if dry_run:
            log.info("  %s: [dry-run] would pull --ff-only on %s", name, branch)
        else:
            log.debug("  %s: pulling --ff-only on %s", name, branch)
            repo.git.pull("--ff-only")
    else:
        if dry_run:
            log.info("  %s: [dry-run] would fetch origin %s:%s", name, branch, branch)
        else:
            log.debug("  %s: fetching origin %s:%s", name, branch, branch)
            repo.git.fetch("origin", f"{branch}:{branch}")

    return True


def _try_rebase(repo: Repo, current: str, target: str, dry_run: bool) -> None:
    """Attempt a fast-forward rebase of the current branch onto target."""
    log = get_logger()
    name = Path(repo.working_dir).name

    if dry_run:
        log.info("  %s: [dry-run] would rebase %s onto %s", name, current, target)
        return

    try:
        log.debug("  %s: rebasing %s onto %s", name, current, target)
        repo.git.rebase(target)
        log.info("  %s: rebased %s onto %s", name, current, target)
    except GitCommandError:
        repo.git.rebase("--abort")
        log.info("  %s: rebase of %s onto %s had conflicts, aborted", name, current, target)


# ---------------------------------------------------------------------------
# Single-repo orchestrator
# ---------------------------------------------------------------------------

def _update_single_repo(
    cached: CachedRepo,
    config: Config,
    dry_run: bool = False,
) -> RepoResult:
    log = get_logger()

    repo, current, early_result = _validate_repo(cached)
    if early_result is not None:
        return early_result

    branches_updated: list[str] = []
    branches_failed: list[str] = []

    for branch in cached.matching_branches:
        try:
            _update_branch(repo, branch, current, dry_run)
            branches_updated.append(branch)
        except GitCommandError as exc:
            msg = exc.stderr.strip() if exc.stderr else str(exc)
            log.warning("  %s: failed to update %s: %s", Path(cached.path).name, branch, msg)
            branches_failed.append(branch)

    if config.fast_forward_rebase and current not in cached.matching_branches and branches_updated:
        _try_rebase(repo, current, branches_updated[0], dry_run)

    if branches_updated and not branches_failed:
        return RepoResult(
            path=cached.path,
            status=RepoStatus.UPDATED,
            branches_updated=branches_updated,
        )
    if branches_updated and branches_failed:
        return RepoResult(
            path=cached.path,
            status=RepoStatus.UPDATED,
            branches_updated=branches_updated,
            branches_failed=branches_failed,
            message=f"Partial: {len(branches_failed)} branch(es) failed",
        )
    if branches_failed:
        return RepoResult(
            path=cached.path,
            status=RepoStatus.ERROR,
            branches_failed=branches_failed,
            message="All branch updates failed",
        )
    return RepoResult(
        path=cached.path,
        status=RepoStatus.SKIPPED,
        message="No branches updated",
    )


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------

def run_update(
    cache: RepoCache,
    config: Config,
    dry_run: bool = False,
) -> RunResult:
    """Execute the full update cycle across all cached repos.

    1. Probe connectivity using the first repo.
    2. If the probe fails, abort immediately.
    3. Otherwise, iterate all cached repos and update matching branches.
    """
    log = get_logger()
    result = RunResult(total=len(cache.repos))

    if not cache.repos:
        log.info("No repos in cache, nothing to update")
        return result

    log.info("Probing connectivity via %s ...", Path(cache.repos[0].path).name)
    if not probe_connectivity(cache.repos[0].path):
        log.warning("Connectivity check failed — aborting this run")
        result.aborted = True
        result.abort_reason = "Network unreachable (connectivity probe failed)"
        return result

    log.info("Updating %d repo(s) ...", len(cache.repos))

    for cached in cache.repos:
        repo_result = _update_single_repo(cached, config, dry_run=dry_run)
        result.results.append(repo_result)

        if repo_result.status == RepoStatus.UPDATED:
            result.updated += 1
        elif repo_result.status == RepoStatus.SKIPPED:
            result.skipped += 1
        else:
            result.errors += 1

    log.info(
        "Run complete: %d updated, %d skipped, %d errors",
        result.updated, result.skipped, result.errors,
    )
    return result
