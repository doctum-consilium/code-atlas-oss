"""Hybrid search: words (BM25) + meaning (vectors) + exact symbol, fused by RRF then reranked.

RRF (*Reciprocal Rank Fusion*): each list gives ``1 / (60 + rank)`` to every chunk it holds, and
the scores add up. A chunk ranked well in two lists beats a chunk ranked first in only one. The
reranker then reads the question and each chunk together and reorders the top 30.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from psycopg import sql

from atlas import lexicon
from atlas.db import vector_literal
from atlas.indexer import context
from atlas.models import Embedder, Reranker

K_RRF = 60
CANDIDATES = 50
TO_RERANK = 30

Mode = Literal["hybrid", "lexical", "vector"]


@dataclass(frozen=True)
class Filters:
    """Optional restrictions; an empty tuple does not filter."""

    repos: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()

    def sql(self) -> tuple[sql.Composable, list[Any]]:
        """``AND …`` clause and its parameters (values are always bound, never concatenated)."""
        parts: list[sql.Composable] = []
        values: list[Any] = []
        for column, items in (
            ("repo", self.repos),
            ("language", self.languages),
            ("type", self.types),
            ("owner", self.owners),
        ):
            if items:
                parts.append(sql.SQL("AND {} = ANY(%s)").format(sql.Identifier(column)))
                values.append(list(items))
        return sql.SQL(" ").join(parts), values


@dataclass
class Result:
    """A chunk found, ready to show or cite."""

    id: int
    repo: str
    path: str
    language: str
    type: str
    kind: str
    symbol: str | None
    line_start: int
    line_end: int
    text: str
    url: str | None
    local_only: bool
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)


def rrf(lists: dict[str, list[int]], k: int = K_RRF) -> list[tuple[int, float]]:
    """Fuse rankings (best first); ties keep arrival order."""
    scores: dict[int, float] = {}
    for ranking in lists.values():
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])


def search(
    connection: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker | None,
    question: str,
    filters: Filters | None = None,
    *,
    k: int = 10,
    mode: Mode = "hybrid",
    links: Mapping[str, str] | None = None,
) -> list[Result]:
    """The ``k`` most relevant chunks for ``question``."""
    filters = filters or Filters()
    lists: dict[str, list[int]] = {}
    if mode in ("hybrid", "lexical"):
        lists["words"] = _lexical(connection, question, filters)
        lists["symbol"] = _symbols(connection, question, filters)
    if mode in ("hybrid", "vector"):
        lists["meaning"] = _vectors(connection, embedder.query(question), filters)
    fused = rrf(lists)
    kept = fused[: TO_RERANK if reranker else k]
    rows = _load(connection, [i for i, _s in kept], links)
    results = []
    for item, score in kept:
        if item in rows:
            r = rows[item]
            r.score = score
            r.ranks = {
                name: ranking.index(item) + 1 for name, ranking in lists.items() if item in ranking
            }
            results.append(r)
    if reranker and results:
        scores = reranker.score(
            question, [f"{context(r.repo, r.path, r.symbol)}\n{r.text[:2000]}" for r in results]
        )
        for r, s in zip(results, scores, strict=True):
            r.score = s
        results.sort(key=lambda r: -r.score)
    return results[:k]


def _lexical(connection: psycopg.Connection, question: str, filters: Filters) -> list[int]:
    terms = lexicon.lexical_query(question)
    if not terms:
        return []
    clause, values = filters.sql()
    query = sql.SQL(
        "SELECT id FROM chunks WHERE lexical @@@ paradedb.match('lexical', %s) {} "
        "ORDER BY paradedb.score(id) DESC LIMIT {}"
    ).format(clause, sql.Literal(CANDIDATES))
    with connection.cursor() as cursor:
        cursor.execute(query, [terms, *values])
        return [int(row[0]) for row in cursor.fetchall()]


def _symbols(connection: psycopg.Connection, question: str, filters: Filters) -> list[int]:
    names = [n.lower() for n in lexicon.identifiers(question)]
    if not names:
        return []
    clause, values = filters.sql()
    query = sql.SQL(
        "SELECT id FROM chunks WHERE (lower(symbol) = ANY(%s) OR lower(symbol) LIKE ANY(%s)) "
        "{} ORDER BY length(text) DESC LIMIT {}"
    ).format(clause, sql.Literal(CANDIDATES))
    with connection.cursor() as cursor:
        cursor.execute(query, [names, [f"%.{n}" for n in names], *values])
        return [int(row[0]) for row in cursor.fetchall()]


def _vectors(connection: psycopg.Connection, vector: list[float], filters: Filters) -> list[int]:
    clause, values = filters.sql()
    query = sql.SQL(
        "SELECT id FROM chunks WHERE TRUE {} ORDER BY embedding <=> %s::vector LIMIT {}"
    ).format(clause, sql.Literal(CANDIDATES))
    with connection.cursor() as cursor:
        cursor.execute(query, [*values, vector_literal(vector)])
        return [int(row[0]) for row in cursor.fetchall()]


def load_chunk(
    connection: psycopg.Connection, chunk_id: int, links: Mapping[str, str] | None = None
) -> Result | None:
    """One chunk by id, or ``None``."""
    return _load(connection, [chunk_id], links).get(chunk_id)


def _load(
    connection: psycopg.Connection, ids: list[int], links: Mapping[str, str] | None
) -> dict[int, Result]:
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.id, c.repo, c.path, c.language, c.type, c.kind, c.symbol, c.line_start,
                      c.line_end, c.text, r.host, r.commit, r.local_only
               FROM chunks c JOIN repos r ON r.key = c.repo WHERE c.id = ANY(%s)""",
            (ids,),
        )
        results = {}
        for (
            i,
            repo,
            path,
            language,
            type_,
            kind,
            symbol,
            start,
            end,
            text,
            host,
            commit,
            local,
        ) in cursor.fetchall():
            results[int(i)] = Result(
                int(i),
                repo,
                path,
                language,
                type_,
                kind,
                symbol,
                start,
                end,
                text,
                source_link(links or {}, host, repo, commit, path, start, end, kind),
                bool(local),
            )
        return results


def source_link(
    links: Mapping[str, str],
    host: str | None,
    repo: str,
    commit: str,
    path: str,
    start: int,
    end: int,
    kind: str = "",
) -> str | None:
    """Link to the exact lines at the indexed commit, from the host's template; ``None`` for a
    repository without a known host. Notebook cells get no line anchor."""
    template = links.get(host or "")
    if not template:
        return None
    url = template.format(repo=repo, commit=commit or "HEAD", path=path, start=start, end=end)
    return url.split("#", 1)[0] if kind == "cell" else url
