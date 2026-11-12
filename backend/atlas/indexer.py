"""Incremental indexing: from the corpus manifest to chunks in the database.

A file is read again only if its git hash (blob) changed; a file gone from the manifest is
removed with its chunks. An interrupted run resumes where it stopped: each batch of files is
committed as soon as it is written.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from atlas import lexicon, secrets, thermal
from atlas.chunking import Chunk, chunk
from atlas.db import vector_literal
from atlas.models import Embedder

BATCH = 256
SYMBOL_MAX = 200  # a Markdown heading trail can be endless; B-tree index entries are bounded


@dataclass
class Summary:
    """What an indexing run did."""

    repos: int = 0
    files_read: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    repos_removed: int = 0
    chunks_added: int = 0
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0


@dataclass(frozen=True)
class _File:
    repo: str
    owner: str
    path: str
    blob: str
    language: str
    type: str
    masked: tuple[int, ...]
    absolute: Path


def context(repo: str, path: str, symbol: str | None) -> str:
    """Header line added to the embedded text: situates the chunk for the embedder."""
    return f"{repo} · {path}" + (f" · {symbol}" if symbol else "")


def index(
    manifest: dict[str, Any],
    connection: psycopg.Connection,
    embedder: Embedder,
    *,
    repos: Iterable[str] | None = None,
    force: bool = False,
    progress: Callable[[str], None] = lambda _m: None,
) -> Summary:
    """Bring the database up to date with ``manifest`` (output of ``atlas corpus``)."""
    start = time.monotonic()
    summary = Summary()
    chosen = set(repos) if repos is not None else None
    infos = {r["key"]: r for r in manifest["repos"]}
    if chosen is None:
        summary.repos_removed = _remove_missing_repos(connection, set(infos))
    by_repo: dict[str, list[dict[str, Any]]] = {}
    for f in manifest["files"]:
        by_repo.setdefault(f["repo"], []).append(f)

    for key, info in infos.items():
        if chosen is not None and key not in chosen:
            continue
        summary.repos += 1
        _save_repo(connection, info)
        known = _known_files(connection, key)
        to_read: list[_File] = []
        present = set()
        for f in by_repo.get(key, []):
            present.add(f["path"])
            previous = known.get(f["path"])
            if previous and previous[1] == f["blob"] and not force:
                summary.files_unchanged += 1
                continue
            to_read.append(
                _File(
                    key,
                    key.split("/", 1)[0],
                    f["path"],
                    f["blob"],
                    f["language"],
                    f["type"],
                    tuple(f.get("masked_lines", [])),
                    Path(info["path"]) / f["path"],
                )
            )
        gone = [file_id for path, (file_id, _b) in known.items() if path not in present]
        if gone:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM files WHERE id = ANY(%s)", (gone,))
            summary.files_removed += len(gone)
        _write(connection, embedder, to_read, summary)
        connection.commit()
        progress(f"{key}: {len(to_read)} files read, {len(gone)} removed")
    summary.duration_s = time.monotonic() - start
    return summary


def _remove_missing_repos(connection: psycopg.Connection, kept: set[str]) -> int:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM repos WHERE NOT (key = ANY(%s))", (list(kept),))
        removed = cursor.rowcount
    connection.commit()
    return removed


def _save_repo(connection: psycopg.Connection, info: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO repos (key, host, path, commit, local_only) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (key) DO UPDATE SET host = EXCLUDED.host, path = EXCLUDED.path,
               commit = EXCLUDED.commit, local_only = EXCLUDED.local_only, indexed_at = now()""",
            (
                info["key"],
                info.get("host"),
                info["path"],
                info.get("commit", ""),
                info.get("local_only", False),
            ),
        )


def _known_files(connection: psycopg.Connection, repo: str) -> dict[str, tuple[int, str]]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT path, id, blob FROM files WHERE repo = %s", (repo,))
        return {path: (file_id, blob) for path, file_id, blob in cursor.fetchall()}


def file_chunks(file: _File) -> list[Chunk]:
    """Read, mask the lines holding secrets, then chunk."""
    text = file.absolute.read_text(encoding="utf-8", errors="replace")
    return chunk(secrets.mask(text, file.masked), file.language, file.path)


def _write(
    connection: psycopg.Connection, embedder: Embedder, files: list[_File], summary: Summary
) -> None:
    pending: list[tuple[int, _File, Chunk]] = []
    for file in files:
        try:
            chunks = file_chunks(file)
        except OSError as error:
            summary.errors.append(f"{file.repo}/{file.path}: {error.strerror}")
            continue
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM files WHERE repo = %s AND path = %s", (file.repo, file.path)
            )
            cursor.execute(
                """INSERT INTO files (repo, path, blob, language, type, masked_lines)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (file.repo, file.path, file.blob, file.language, file.type, list(file.masked)),
            )
            row = cursor.fetchone()
        assert row is not None  # noqa: S101 -- RETURNING always yields a row
        summary.files_read += 1
        pending += [(int(row[0]), file, c) for c in chunks]
        if len(pending) >= BATCH:
            _flush(connection, embedder, pending, summary)
            pending = []
    _flush(connection, embedder, pending, summary)


def _flush(
    connection: psycopg.Connection,
    embedder: Embedder,
    pending: list[tuple[int, _File, Chunk]],
    summary: Summary,
) -> None:
    if not pending:
        return
    to_embed = [f"{context(f.repo, f.path, c.symbol)}\n{c.text}" for _i, f, c in pending]
    thermal.GUARD.wait()  # a batch of vectors heats the GPU: pause if needed
    vectors = embedder.documents(to_embed)
    rows = [
        (
            file_id,
            f.repo,
            f.owner,
            f.path,
            f.language,
            f.type,
            c.kind,
            (c.symbol or "")[:SYMBOL_MAX] or None,
            c.line_start,
            c.line_end,
            c.text,
            lexicon.lexical_text(f.path, c.symbol, c.text),
            vector_literal(v),
        )
        for (file_id, f, c), v in zip(pending, vectors, strict=True)
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO chunks (file_id, repo, owner, path, language, type, kind, symbol,
               line_start, line_end, text, lexical, embedding)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)""",
            rows,
        )
    connection.commit()
    summary.chunks_added += len(rows)
