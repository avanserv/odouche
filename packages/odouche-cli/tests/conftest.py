import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from odouche_cli._context import BRANCH_ENV, PROJECT_ENV


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run in an empty directory, with neither variable set and no git configuration of the user's."""
    monkeypatch.delenv(PROJECT_ENV, raising=False)
    monkeypatch.delenv(BRANCH_ENV, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    # A stray repository above `tmp_path` is not this test's checkout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)


def _git(*args: str) -> None:
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args], check=True)  # noqa: S603, S607


@pytest.fixture
def git() -> Callable[..., None]:
    """Run a git command in the current directory."""
    return _git


@pytest.fixture
def checkout() -> Callable[..., None]:
    """Make the current directory a repository on `branch`, with one commit and these remotes."""

    def checkout(branch: str = "feature-x", **remotes: str) -> None:
        _git("init", "--quiet", "--initial-branch", branch)
        _git("commit", "--quiet", "--allow-empty", "--message", "first")
        for name, url in remotes.items():
            _git("remote", "add", name, url)

    return checkout
