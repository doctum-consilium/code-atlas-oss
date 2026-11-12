"""Evaluation: does search find the right file, and does the chat cite it?

Two search measures over a questions file (see ``eval/example-questions.yaml``):

- **recall@10**: share of questions where an expected file is among the first 10 chunks;
- **MRR** (*Mean Reciprocal Rank*): mean of ``1 / rank`` of the first chunk from an expected file
  (1 when first, 0.5 when second, 0 when absent from the 10).

For the chat, on a subset: does the answer cite a chunk from an expected file ("right
citation"), how many citations point nowhere, and how fast.
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from atlas import search, thermal
from atlas.models import Embedder, Reranker


@dataclass(frozen=True)
class Question:
    """A question and the files that answer it."""

    id: str
    category: str
    question: str
    expected: tuple[tuple[str, str], ...]


def load(path: Path) -> list[Question]:
    """Read a questions file."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Question(
            q["id"],
            q["category"],
            q["question"],
            tuple((e["repo"], e["path"]) for e in q["expected"]),
        )
        for q in raw["questions"]
    ]


def first_expected_rank(
    results: Sequence[tuple[str, str]], expected: Sequence[tuple[str, str]]
) -> int | None:
    """Rank (from 1) of the first result that is an expected file, else ``None``."""
    targets = set(expected)
    for rank, file in enumerate(results, start=1):
        if file in targets:
            return rank
    return None


@dataclass
class Measure:
    """Scores of one configuration."""

    name: str
    recall: float
    mrr: float
    per_category: dict[str, tuple[float, float]]
    mean_ms: float
    missed: list[str]


def measure(
    name: str, questions: Sequence[Question], find: Callable[[str], list[search.Result]]
) -> Measure:
    """Run ``find`` on every question and aggregate recall@10 and MRR."""
    ranks: dict[str, int | None] = {}
    durations = []
    for q in questions:
        thermal.GUARD.wait()
        start = time.monotonic()
        results = find(q.question)
        durations.append((time.monotonic() - start) * 1000)
        ranks[q.id] = first_expected_rank([(r.repo, r.path) for r in results], q.expected)
    groups: dict[str, list[int | None]] = defaultdict(list)
    for q in questions:
        groups[q.category].append(ranks[q.id])
    return Measure(
        name=name,
        recall=_recall(list(ranks.values())),
        mrr=_mrr(list(ranks.values())),
        per_category={c: (_recall(r), _mrr(r)) for c, r in sorted(groups.items())},
        mean_ms=sum(durations) / max(1, len(durations)),
        missed=[q.id for q in questions if ranks[q.id] is None],
    )


def _recall(ranks: list[int | None]) -> float:
    return sum(1 for r in ranks if r is not None) / max(1, len(ranks))


def _mrr(ranks: list[int | None]) -> float:
    return sum(1 / r for r in ranks if r is not None) / max(1, len(ranks))


def configurations(
    connection: psycopg.Connection, embedder: Embedder, reranker: Reranker | None
) -> dict[str, Callable[[str], list[search.Result]]]:
    """The compared configurations."""

    def make(mode: search.Mode, rerank: bool) -> Callable[[str], list[search.Result]]:
        return lambda question: search.search(
            connection, embedder, reranker if rerank else None, question, k=10, mode=mode
        )

    configs = {
        "words only (BM25)": make("lexical", False),
        "meaning only (vectors)": make("vector", False),
        "hybrid (RRF)": make("hybrid", False),
    }
    if reranker is not None:
        configs["hybrid + reranker"] = make("hybrid", True)
    return configs


def table(measures: Sequence[Measure]) -> str:
    """Markdown table of the measures, then the per-category detail."""
    lines = ["| Configuration | Recall@10 | MRR | Mean time |", "|---|---:|---:|---:|"]
    lines += [f"| {m.name} | {m.recall:.0%} | {m.mrr:.2f} | {m.mean_ms:.0f} ms |" for m in measures]
    categories = sorted({c for m in measures for c in m.per_category})
    lines += [
        "",
        "| Category | " + " | ".join(m.name for m in measures) + " |",
        "|---|" + "---:|" * len(measures),
    ]
    for c in categories:
        cells = []
        for m in measures:
            recall, mrr = m.per_category.get(c, (0.0, 0.0))
            cells.append(f"{recall:.0%} · {mrr:.2f}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def evaluate_chat(
    connection: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker | None,
    questions: Sequence[Question],
    settings: Any,
    model_names: Sequence[str] = (),
) -> str:
    """For each local model: right citations, citations pointing nowhere, speed."""
    from atlas import chat

    lines = [
        "| Model | Right citation | Citations outside chunks | Chars/s | Mean time |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in model_names or settings.models.local:
        right = nowhere = chars = 0
        duration = 0.0
        target = chat.Target("local", model, f"{settings.models.local_url}/v1", None, "local")
        for q in questions:
            thermal.GUARD.wait()
            chunks = search.search(connection, embedder, reranker, q.question, k=8)
            start = time.monotonic()
            text = "".join(
                chat.stream(
                    target, chat.build_messages(q.question, chunks, language=settings.language)
                )
            )
            duration += time.monotonic() - start
            chars += len(text)
            valid, invalid = chat.citations(text, len(chunks))
            nowhere += len(invalid)
            cited = {(chunks[n - 1].repo, chunks[n - 1].path) for n in valid}
            right += bool(cited & set(q.expected))
        n = max(1, len(questions))
        lines.append(
            f"| {model} | {right / n:.0%} | {nowhere} | "
            f"{chars / max(duration, 1e-6):.0f} | {duration / n:.1f} s |"
        )
    return "\n".join(lines)


def cmd_eval(args: argparse.Namespace) -> int:
    """Measure search (and chat with ``--chat``); write the Markdown result."""
    from atlas import cli

    questions = load(Path(args.questions))
    settings = cli._settings()
    embedder = cli.embedder_for(settings, args.fake)
    reranker = cli.reranker_for(settings, args.fake)
    with cli.open_db(settings) as connection:
        measures = [
            measure(name, questions, f)
            for name, f in configurations(connection, embedder, reranker).items()
        ]
        text = [f"# Search evaluation ({len(questions)} questions)", "", table(measures), ""]
        best = max(measures, key=lambda m: (m.mrr, m.recall))
        text += [f"Questions missed by « {best.name} »: " + (", ".join(best.missed) or "none"), ""]
        if args.chat:
            text += [
                "## Local chat",
                "",
                evaluate_chat(
                    connection,
                    embedder,
                    reranker,
                    questions[: args.chat],
                    settings,
                    args.model or (),
                ),
                "",
            ]
    Path(args.output).write_text("\n".join(text), encoding="utf-8")
    print("\n".join(text))
    return 0


def add_command(sub: Any) -> None:
    """Add ``atlas eval``."""
    p = sub.add_parser("eval", help="measure search on a questions file")
    p.add_argument("--questions", required=True)
    p.add_argument("--output", default="eval-results.md")
    p.add_argument("--chat", type=int, default=0, help="also evaluate the chat on N questions")
    p.add_argument("--model", action="append", help="limit the chat to this local model")
    p.add_argument("--fake", action="store_true")
    p.set_defaults(func=cmd_eval)
