"""Shared fixtures: test database, a small real corpus on disk, settings."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from atlas import corpus, db

TABLES = ("messages", "conversations", "chunks", "files", "repos")
DIMENSION = 1024


@pytest.fixture
def connection() -> Iterator[psycopg.Connection]:
    """Empty ParadeDB database with the schema. No database: skipped locally, failure in CI."""
    dsn = os.environ.get("CODE_ATLAS_TEST_DSN")
    if not dsn:
        if os.environ.get("CI"):
            pytest.fail("CODE_ATLAS_TEST_DSN is required in CI")
        pytest.skip("no test database (CODE_ATLAS_TEST_DSN)")
    with psycopg.connect(dsn) as c:
        with c.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE")
        c.commit()
        db.migrate(c, DIMENSION)
        db.tune_hnsw(c)
        yield c


def make_repo(root: Path, name: str, files: dict[str, str], remote: str | None = None) -> Path:
    """A small real git repository (files added to the index)."""
    path = root / name
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    for relative, content in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if files:
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    return path


def blob(repo: Path, relative: str) -> str:
    """Git hash of a file."""
    out = subprocess.run(
        ["git", "-C", str(repo), "hash-object", relative],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


SAMPLE_FILES = {
    "app/sharing.py": (
        "def can_receive_shared_feed(account):\n"
        '    """Only the owner receives the shared feed."""\n'
        "    return account.is_owner\n\n\n"
        "class Risk:\n"
        "    def sized_stop(self, target_gain):\n"
        "        return target_gain / 2\n"
    ),
    "docs/plan.md": (
        "# Plan\n\nReciprocal rank fusion combines the rankings.\n\n"
        "## Reranker\n\nIt reads again.\n"
    ),
    "k8s/app.yaml": "apiVersion: v1\nkind: Service\nmetadata:\n  name: atlas\n",
}


def manifest_for(
    repo: Path, key: str, files: dict[str, str], host: str | None = "github.com", **extra: Any
) -> dict[str, Any]:
    """Minimal manifest (shape of ``atlas corpus``) for a test repository."""
    entries = []
    for relative in files:
        language, type_ = corpus.classify(relative) or ("", "")
        entries.append(
            {
                "repo": key,
                "path": relative,
                "blob": blob(repo, relative),
                "size": 1,
                "language": language,
                "type": type_,
                "masked_lines": [],
            }
        )
    return {
        "repos": [
            {
                "key": key,
                "host": host,
                "path": str(repo),
                "commit": "abc123",
                "local_only": extra.get("local_only", False),
            }
        ],
        "files": entries,
    }
