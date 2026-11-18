"""Throwaway test repositories stay isolated from the repository of a calling git hook.

A hook (pre-commit, pre-push) run from a linked worktree exports ``GIT_DIR`` and
``GIT_INDEX_FILE`` pointing at the real repository. Inherited, they make
``git -C <throwaway> init`` and ``git -C <throwaway> add`` write into that real repository:
``git -C`` does not isolate the inherited git environment.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas import corpus

BACKEND = Path(__file__).resolve().parents[1]

# Identity of the witness's single commit: it lives here, never in a typed command.
WITNESS_IDENTITY = ("-c", "user.name=Witness", "-c", "user.email=witness@example.test")


def _env_without_git() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_") or name == "GIT_EXEC_PATH"
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_env_without_git(),
    )
    return result.stdout.strip()


def _state(witness: Path) -> tuple[str, str, str, str]:
    """Commits, core.bare, index hash and remotes of the witness."""
    index = hashlib.sha256((witness / ".git" / "index").read_bytes()).hexdigest()
    return (
        _git(witness, "rev-list", "--all"),
        _git(witness, "config", "--get", "core.bare"),
        index,
        _git(witness, "remote"),
    )


def test_a_git_hook_does_not_make_the_tests_write_into_its_repository(tmp_path: Path) -> None:
    witness = tmp_path / "witness"
    witness.mkdir()
    _git(witness, "init", "-q")
    (witness / "tracked.txt").write_text("content of the real repository\n", encoding="utf-8")
    _git(witness, "add", "tracked.txt")
    _git(witness, *WITNESS_IDENTITY, "commit", "-q", "-m", "witness")
    before = _state(witness)

    # What a hook run from a linked worktree of the witness exports.
    env = _env_without_git()
    env["GIT_DIR"] = str(witness / ".git")
    env["GIT_INDEX_FILE"] = str(witness / ".git" / "index")
    env["GIT_AUTHOR_NAME"] = "Hook"
    env["GIT_AUTHOR_EMAIL"] = "hook@example.test"
    suite = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-cov",
            "-m",
            "not db",
            f"--basetemp={tmp_path / 'suite'}",
            "tests/test_corpus.py",
            "tests/test_support.py",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert _state(witness) == before, "the tests wrote into the hook's repository"
    assert _git(witness, "ls-files") == "tracked.txt"
    assert suite.returncode == 0, suite.stdout[-3000:] + suite.stderr[-3000:]


def test_the_corpus_reads_the_requested_repository_even_under_a_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    witness = tmp_path / "witness"
    witness.mkdir()
    _git(witness, "init", "-q")
    (witness / "from_hook.py").write_text("x = 1\n", encoding="utf-8")
    _git(witness, "add", "from_hook.py")
    read = tmp_path / "read"
    read.mkdir()
    _git(read, "init", "-q")
    (read / "read.py").write_text("y = 2\n", encoding="utf-8")
    _git(read, "add", "read.py")

    monkeypatch.setenv("GIT_DIR", str(witness / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(witness / ".git" / "index"))

    assert [e.path for e in corpus.list_tracked(read)] == ["read.py"]


def test_git_environment_keeps_only_neutral_variables() -> None:
    base = {
        "GIT_DIR": "/real/.git",
        "GIT_INDEX_FILE": "/real/.git/index",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.bare",
        "GIT_CONFIG_VALUE_0": "true",
        "GIT_COMMITTER_NAME": "Hook",
        "GIT_EXEC_PATH": "/usr/lib/git-core",
        "HOME": "/home/someone",
    }
    assert corpus.git_environment(base) == {
        "GIT_EXEC_PATH": "/usr/lib/git-core",
        "HOME": "/home/someone",
    }
