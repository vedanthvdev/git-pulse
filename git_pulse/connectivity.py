"""Connectivity probe for git-pulse.

Performs a lightweight remote check before processing repos to avoid
wasting time when the network or VPN is down.
"""

from __future__ import annotations

from git import GitCommandError, Repo

from git_pulse.logger import get_logger


def probe_connectivity(repo_path: str, timeout: int = 15) -> bool:
    """Try a lightweight remote check against the first cached repo.

    Uses `git ls-remote --exit-code origin HEAD` which only reads a
    single ref from the remote — fast and doesn't modify anything.

    Returns True if the network is reachable, False otherwise.
    """
    log = get_logger()
    try:
        repo = Repo(repo_path)
        repo.git.ls_remote("--exit-code", "origin", "HEAD")
        log.debug("Connectivity probe succeeded via %s", repo_path)
        return True
    except GitCommandError as exc:
        log.warning(
            "Connectivity probe failed via %s: %s", repo_path, exc.stderr.strip() if exc.stderr else str(exc)
        )
        return False
    except Exception as exc:
        log.warning("Connectivity probe error: %s", exc)
        return False
