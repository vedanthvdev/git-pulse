"""Reusable helpers for creating test git repositories.

Used across integration and e2e tests that need real git repos on disk.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from git import Repo


def make_bare_remote(path: Path, default_branch: str = "master") -> Repo:
    """Create a bare repo that acts as an 'origin' remote."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", f"--initial-branch={default_branch}", str(path)],
        capture_output=True,
        check=True,
    )
    return Repo(str(path))


def make_local_repo(
    path: Path,
    remote_path: Path,
    default_branch: str = "master",
) -> Repo:
    """Clone from a bare remote, configure git user, create an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(remote_path), str(path)],
        capture_output=True,
        check=True,
    )
    repo = Repo(str(path))
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    (path / "README.md").write_text("# Test repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    repo.git.push("origin", default_branch)
    return repo


def push_remote_commit(
    remote_path: Path,
    branch: str = "master",
    filename: str = "new_file.txt",
    content: str = "new content\n",
    message: str = "Remote commit",
) -> None:
    """Clone the bare remote, commit, push — simulates someone else pushing."""
    clone_dir = remote_path.parent / "_temp_push_clone"
    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    subprocess.run(
        ["git", "clone", str(remote_path), str(clone_dir)],
        capture_output=True,
        check=True,
    )
    temp = Repo(str(clone_dir))
    temp.config_writer().set_value("user", "name", "Other").release()
    temp.config_writer().set_value("user", "email", "other@test.com").release()

    (clone_dir / filename).write_text(content)
    temp.index.add([filename])
    temp.index.commit(message)
    temp.git.push("origin", branch)

    shutil.rmtree(clone_dir)


def create_repo_pair(
    tmp_path: Path,
    name: str,
    default_branch: str = "master",
) -> tuple[Path, Path, Repo]:
    """Convenience: create a bare remote + cloned local repo, return (remote, local, repo)."""
    remote = tmp_path / "remotes" / f"{name}.git"
    local = tmp_path / "repos" / name
    make_bare_remote(remote, default_branch)
    repo = make_local_repo(local, remote, default_branch)
    return remote, local, repo
