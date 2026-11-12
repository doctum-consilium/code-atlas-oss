"""Incremental indexing and hybrid search on a real ParadeDB database."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from atlas import db, indexer, search
from atlas.config import CorpusSettings
from atlas.models import FakeEmbedder, FakeReranker
from tests.conftest import SAMPLE_FILES, blob, make_repo, manifest_for

KEY = "acme/sample"
LINKS = CorpusSettings().links


def _count(c: psycopg.Connection, table: str) -> int:
    with c.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 -- fixed test table name
        row = cur.fetchone()
    return int(row[0]) if row else 0


def test_rrf_without_database() -> None:
    fused = search.rrf({"a": [1, 2, 3], "b": [3, 1]})
    assert [i for i, _s in fused] == [1, 3, 2]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


@pytest.mark.parametrize(
    ("host", "kind", "expected"),
    [
        ("github.com", "function", "https://github.com/acme/api/blob/abc/a.py#L3-L9"),
        ("gitlab.com", "function", "https://gitlab.com/acme/api/-/blob/abc/a.py#L3-9"),
        ("github.com", "cell", "https://github.com/acme/api/blob/abc/a.py"),
        (None, "function", None),
        ("git.example.org", "function", None),
    ],
)
def test_source_links(host: str | None, kind: str, expected: str | None) -> None:
    assert search.source_link(LINKS, host, "acme/api", "abc", "a.py", 3, 9, kind) == expected


@pytest.fixture
def indexed(connection: psycopg.Connection, tmp_path: Path) -> tuple[psycopg.Connection, Path]:
    repo = make_repo(tmp_path, "sample", SAMPLE_FILES)
    summary = indexer.index(manifest_for(repo, KEY, SAMPLE_FILES), connection, FakeEmbedder())
    assert summary.files_read == 3 and summary.chunks_added >= 4
    return connection, repo


@pytest.mark.db
def test_exact_symbol_search(indexed: tuple[psycopg.Connection, Path]) -> None:
    c, _ = indexed
    results = search.search(
        c, FakeEmbedder(), None, "what does can_receive_shared_feed do?", links=LINKS
    )
    first = results[0]
    assert (first.path, first.symbol, first.line_start) == (
        "app/sharing.py",
        "can_receive_shared_feed",
        1,
    )
    assert {"words", "symbol", "meaning"} <= set(first.ranks)
    assert first.url == "https://github.com/acme/sample/blob/abc123/app/sharing.py#L1-L3"


@pytest.mark.db
def test_natural_language_search_with_reranker(indexed: tuple[psycopg.Connection, Path]) -> None:
    c, _ = indexed
    results = search.search(
        c, FakeEmbedder(), FakeReranker(), "how to size the stop from the target gain", k=3
    )
    assert "Risk" in {r.symbol for r in results}  # a short class stays one chunk


@pytest.mark.db
@pytest.mark.parametrize("mode", ["lexical", "vector", "hybrid"])
def test_filters(indexed: tuple[psycopg.Connection, Path], mode: search.Mode) -> None:
    c, _ = indexed
    results = search.search(
        c,
        FakeEmbedder(),
        None,
        "reciprocal rank fusion reranker",
        search.Filters(types=("doc",)),
        mode=mode,
    )
    assert results and {r.type for r in results} == {"doc"}
    assert (
        search.search(
            c, FakeEmbedder(), None, "fusion", search.Filters(repos=("other/repo",)), mode=mode
        )
        == []
    )


@pytest.mark.db
def test_question_without_useful_word(indexed: tuple[psycopg.Connection, Path]) -> None:
    c, _ = indexed
    assert search.search(c, FakeEmbedder(), None, "where is the ?", mode="lexical") == []
    assert search.load_chunk(c, 999_999) is None


@pytest.mark.db
def test_reindex_reads_only_what_changed(indexed: tuple[psycopg.Connection, Path]) -> None:
    c, repo = indexed
    files = dict(SAMPLE_FILES)
    summary = indexer.index(manifest_for(repo, KEY, files), c, FakeEmbedder())
    assert (summary.files_read, summary.files_unchanged) == (0, 3)

    (repo / "docs/plan.md").write_text("# Plan\n\nNew text about fusion.\n", encoding="utf-8")
    del files["k8s/app.yaml"]
    files["docs/plan.md"] = "changed"
    manifest = manifest_for(repo, KEY, files)
    assert blob(repo, "docs/plan.md") in {f["blob"] for f in manifest["files"]}
    summary = indexer.index(manifest, c, FakeEmbedder())
    assert (summary.files_read, summary.files_unchanged, summary.files_removed) == (1, 1, 1)
    assert _count(c, "files") == 2
    assert indexer.index(manifest, c, FakeEmbedder(), force=True).files_read == 2


@pytest.mark.db
def test_repo_leaving_the_corpus_is_removed(indexed: tuple[psycopg.Connection, Path]) -> None:
    c, _ = indexed
    assert indexer.index({"repos": [], "files": []}, c, FakeEmbedder()).repos_removed == 1
    assert _count(c, "chunks") == 0


@pytest.mark.db
def test_secret_lines_are_masked_before_indexing(
    connection: psycopg.Connection, tmp_path: Path
) -> None:
    files = {"conf.py": "name = 'atlas'\npassword = 'very-secret-value'\nport = 1\n"}
    repo = make_repo(tmp_path, "s", files)
    manifest = manifest_for(repo, KEY, files)
    manifest["files"][0]["masked_lines"] = [2]
    indexer.index(manifest, connection, FakeEmbedder())
    with connection.cursor() as cur:
        cur.execute("SELECT text || lexical FROM chunks")
        everything = " ".join(t for (t,) in cur.fetchall())
    assert "very-secret-value" not in everything and "line masked" in everything


@pytest.mark.db
def test_missing_file_is_reported(connection: psycopg.Connection, tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "e", {"a.py": "x = 1\n"})
    manifest = manifest_for(repo, KEY, {"a.py": ""})
    (repo / "a.py").unlink()
    summary = indexer.index(manifest, connection, FakeEmbedder(), repos=[KEY])
    assert summary.errors and "a.py" in summary.errors[0]


@pytest.mark.db
def test_long_symbols_are_capped(connection: psycopg.Connection, tmp_path: Path) -> None:
    title = "x" * 900
    files = {"long.md": f"# {title}\n\ntext\n"}
    repo = make_repo(tmp_path, "l", files)
    indexer.index(manifest_for(repo, KEY, files), connection, FakeEmbedder())
    with connection.cursor() as cur:
        cur.execute("SELECT max(length(symbol)) FROM chunks")
        row = cur.fetchone()
    assert row is not None and row[0] == indexer.SYMBOL_MAX


@pytest.mark.db
def test_dimension_mismatch_is_detected(connection: psycopg.Connection) -> None:
    with pytest.raises(db.DimensionMismatch, match="1024-dimension"):
        db.migrate(connection, 384)
    with pytest.raises(ValueError, match="Unsupported"):
        db.migrate(connection, 0)
