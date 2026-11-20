"""Clone each repository once and check out base commits on demand.

Strategy (see CLAUDE.md §3.1): one working copy per repo under DATA_DIR/raw/repos/<owner>__<name>.
For each instance we `git checkout --force <base_commit>` in that folder, process it, then move on.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from semnav_gp.helpers.logging import get_logger

log = get_logger(__name__)


class GitError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def repo_path(repos_dir: Path, repo: str) -> Path:
    return repos_dir / repo.replace("/", "__")


def is_cloned(path: Path) -> bool:
    return (path / ".git").is_dir()


def clone_repo(repo: str, repos_dir: Path) -> Path:
    """Full clone (old base commits need full history). Skips if already cloned."""
    path = repo_path(repos_dir, repo)
    if is_cloned(path):
        log.info("Already cloned: %s", repo)
        return path
    url = f"https://github.com/{repo}.git"
    log.info("Cloning %s -> %s (this can take a few minutes)...", url, path)
    _git(["clone", "--no-checkout", url, str(path)])
    _git(["config", "core.longpaths", "true"], cwd=path)
    _git(["config", "core.autocrlf", "false"], cwd=path)  # keep line endings exactly as in the repo
    return path


def has_commit(path: Path, commit: str) -> bool:
    return _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=path, check=False).returncode == 0


def checkout(path: Path, commit: str) -> None:
    """Put the working copy at `commit` (discarding any local changes)."""
    _git(["checkout", "--force", "--quiet", commit], cwd=path)
    _git(["clean", "-fdq"], cwd=path)


def head_commit(path: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd=path).stdout.strip()


def folder_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


@dataclass
class CommitCheck:
    repo: str
    base_commit: str
    found: bool
