"""The ``atlas`` command: corpus, index, search, serve, token, openapi, eval."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psycopg

from atlas import corpus, db, forks, indexer, models, search, secrets, thermal
from atlas.config import Settings


def data_dir() -> Path:
    """``$CODE_ATLAS_DATA`` or ``~/.local/share/code-atlas``."""
    return Path(os.environ.get("CODE_ATLAS_DATA", "~/.local/share/code-atlas")).expanduser()


def cache_dir() -> Path:
    """``$CODE_ATLAS_CACHE`` or ``~/.cache/code-atlas``."""
    return Path(os.environ.get("CODE_ATLAS_CACHE", "~/.cache/code-atlas")).expanduser()


def _settings() -> Settings:
    settings = Settings.load()
    t = settings.thermal
    thermal.configure(t.enabled, t.gpu_max_c, t.cpu_max_c)
    return settings


def build_manifest(
    settings: Settings,
    *,
    refresh_forks: bool = False,
    skip_secrets: bool = False,
    processes: int = 8,
) -> tuple[dict[str, Any], str]:
    """Select the corpus, scan secrets, write ``corpus.json`` and the report.

    Returns:
        The manifest and the report text.
    """
    start = time.monotonic()
    c = settings.corpus
    fork_source = forks.GitHubForks(cache_dir() / "forks.json", refresh=refresh_forks)
    report = corpus.build(c, fork_source)
    fork_source.save()

    alerts: list[secrets.Alert] = []
    if not skip_secrets:
        paths = {d.repo.key: d.repo.path for d in report.kept()}
        alerts = secrets.scan_all(
            ((f"{f.repo}/{f.path}", paths[f.repo] / f.path) for f in report.files),
            processes=processes,
        )
    excluded, masked = secrets.split(alerts)
    files = [f for f in report.files if f"{f.repo}/{f.path}" not in excluded]

    out = data_dir()
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repos": [
            {
                "key": d.repo.key,
                "host": d.repo.host,
                "path": str(d.repo.path),
                "commit": report.commits.get(d.repo.key, ""),
                "local_only": d.repo.key in c.local_only,
            }
            for d in report.kept()
        ],
        "files": [
            asdict(f) | {"masked_lines": masked.get(f"{f.repo}/{f.path}", [])} for f in files
        ],
    }
    (out / "corpus.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    text = write_report(report, files, alerts, masked, excluded, time.monotonic() - start)
    (out / "corpus-report.md").write_text(text, encoding="utf-8")
    return manifest, text


def write_report(
    report: corpus.Report,
    files: list[corpus.File],
    alerts: list[secrets.Alert],
    masked: dict[str, list[int]],
    excluded_files: set[str],
    duration_s: float,
) -> str:
    """Markdown report: kept and excluded repos, skips, duplicates, secrets (paths only)."""
    per_repo = Counter(f.repo for f in files)
    per_type = Counter(f.type for f in files)
    per_language = Counter(f.language for f in files)
    kept = report.kept()
    excluded = [d for d in report.decisions if not d.kept]
    lines = [
        "# code-atlas corpus report",
        "",
        f"- Repositories kept: **{len(kept)}**; excluded: **{len(excluded)}**",
        f"- Files selected: **{len(files)}** "
        f"({', '.join(f'{t} {n}' for t, n in per_type.most_common())})",
        f"- Probable secrets: **{len(masked)}** files with masked lines, "
        f"**{len(excluded_files)}** excluded entirely (private key)",
        f"- Duration: {duration_s:.0f} s",
        "",
        "## Excluded repositories",
        "",
        "| Folder | Repository | Reason |",
        "|---|---|---|",
    ]
    lines += [f"| `{d.repo.path.name}` | {d.repo.key} | {d.reason} |" for d in excluded]
    lines += ["", "## Kept repositories", "", "| Repository | Files |", "|---|---:|"]
    lines += [
        f"| {d.repo.key} | {per_repo[d.repo.key]} |"
        for d in sorted(kept, key=lambda d: -per_repo[d.repo.key])
    ]
    lines += ["", "## Languages", "", "| Language | Files |", "|---|---:|"]
    lines += [f"| {lang} | {n} |" for lang, n in per_language.most_common()]
    lines += ["", "## Skipped files", "", "| Reason | Count |", "|---|---:|"]
    lines += [f"| {r} | {n} |" for r, n in report.skipped.most_common()]
    lines += [
        "",
        "## Probable secrets (line masked or file excluded; value never shown)",
        "",
        "| Detector | Alerts |",
        "|---|---:|",
    ]
    lines += [f"| {d} | {n} |" for d, n in Counter(a.detector for a in alerts).most_common()]
    lines += ["", "### Files excluded entirely", ""]
    lines += [f"- `{p}`" for p in sorted(excluded_files)] or ["None."]
    lines += ["", "### Alert details", ""]
    if alerts:
        lines += ["| File | Detector | Line |", "|---|---|---:|"]
        lines += [f"| `{a.path}` | {a.detector} | {a.line} |" for a in alerts]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def embedder_for(settings: Settings, fake: bool) -> models.Embedder:
    """The configured embedder, or the deterministic fake."""
    m = settings.models
    if fake:
        return models.FakeEmbedder(m.dimension)
    return models.SentenceTransformerEmbedder(m.embedder, m.dimension, m.query_prompt)


def reranker_for(settings: Settings, fake: bool) -> models.Reranker | None:
    """The configured reranker (``None`` if disabled), or the deterministic fake."""
    if fake:
        return models.FakeReranker()
    return (
        models.CrossEncoderReranker(settings.models.reranker) if settings.models.reranker else None
    )


@contextmanager
def open_db(settings: Settings) -> Iterator[psycopg.Connection]:
    """Connection with the schema applied and HNSW tuned."""
    with db.connect(settings.database.dsn()) as connection:
        db.migrate(connection, settings.models.dimension)
        db.tune_hnsw(connection)
        yield connection


def cmd_corpus(args: argparse.Namespace) -> int:
    """Build the corpus manifest and its readable report."""
    _manifest, text = build_manifest(
        _settings(),
        refresh_forks=args.refresh,
        skip_secrets=args.skip_secrets,
        processes=args.processes,
    )
    print(text)
    print(f"Manifest: {data_dir() / 'corpus.json'}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Update the index from the latest manifest (``atlas corpus``)."""
    path = data_dir() / "corpus.json"
    if not path.is_file():
        print("No manifest: run « atlas corpus » first.", file=sys.stderr)
        return 1
    settings = _settings()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    with open_db(settings) as connection:
        summary = indexer.index(
            manifest,
            connection,
            embedder_for(settings, args.fake),
            repos=args.repo or None,
            force=args.force,
            progress=print if args.verbose else lambda _m: None,
        )
    print(
        f"{summary.repos} repos · {summary.files_read} files read · "
        f"{summary.files_unchanged} unchanged · {summary.files_removed} removed · "
        f"{summary.chunks_added} chunks added · {summary.duration_s:.0f} s"
    )
    for error in summary.errors[:20]:
        print(f"  ! {error}", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search in the terminal, without a chat model."""
    settings = _settings()
    reranker = None if args.no_rerank else reranker_for(settings, args.fake)
    filters = search.Filters(repos=tuple(args.repo or ()), languages=tuple(args.language or ()))
    with open_db(settings) as connection:
        results = search.search(
            connection,
            embedder_for(settings, args.fake),
            reranker,
            args.question,
            filters,
            k=args.k,
            mode=args.mode,
            links=settings.corpus.links,
        )
    for n, r in enumerate(results, start=1):
        symbol = f" · {r.symbol}" if r.symbol else ""
        print(f"{n:>2}. {r.repo}/{r.path}:{r.line_start}-{r.line_end}{symbol}  [{r.score:.3f}]")
        if args.excerpts:
            for line in r.text.splitlines()[:6]:
                print(f"      {line[:110]}")
    return 0 if results else 1


def cmd_token(args: argparse.Namespace) -> int:
    """Create the API token file if missing (``token`` mode). Never prints the token."""
    from atlas.auth import create_token_file

    settings = _settings()
    path = Path(settings.auth.token_file).expanduser()
    created = create_token_file(path)
    print(f"API token {'created' if created else 'already present'}: {path} (0600)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the API on the loopback interface only."""
    import uvicorn

    from atlas.server import create_app, real_services, warm_up

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = _settings()
    if settings.host not in ("127.0.0.1", "::1"):
        raise SystemExit("code-atlas only listens on the loopback interface (host = 127.0.0.1).")
    services = real_services(settings)
    if not args.no_warm_up:
        threading.Thread(target=warm_up, args=(services,), daemon=True).start()
    uvicorn.run(
        create_app(services),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    """Write the OpenAPI contract (sorted YAML, stable from one run to the next)."""
    import yaml

    from atlas.auth import TokenVerifier
    from atlas.policy import Gatekeeper, Policy
    from atlas.server import Services, create_app

    @contextmanager
    def no_db() -> Iterator[psycopg.Connection]:
        raise RuntimeError("no database needed to produce the contract")
        yield  # pragma: no cover

    services = Services(
        Settings(),
        no_db,
        models.FakeEmbedder(),
        None,
        TokenVerifier(""),
        Gatekeeper(Policy.empty()),
    )
    text = yaml.safe_dump(
        create_app(services).openapi(), allow_unicode=True, sort_keys=True, width=100
    )
    if args.output == "-":
        print(text, end="")
    else:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``atlas`` command."""
    parser = argparse.ArgumentParser(prog="atlas", description="Search your code repositories.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("corpus", help="select the repositories and files to index")
    p.add_argument("--refresh", action="store_true", help="read fork status again")
    p.add_argument("--skip-secrets", action="store_true", help="skip detect-secrets")
    p.add_argument("--processes", type=int, default=8)
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("index", help="update the index (changed files only)")
    p.add_argument("--repo", action="append", help="limit to this repository (repeatable)")
    p.add_argument("--force", action="store_true", help="read everything again")
    p.add_argument("--fake", action="store_true", help="fake embedder (tests)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search", help="search without a chat model")
    p.add_argument("question")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "lexical", "vector"], default="hybrid")
    p.add_argument("--repo", action="append")
    p.add_argument("--language", action="append")
    p.add_argument("--no-rerank", action="store_true")
    p.add_argument("--excerpts", action="store_true", help="show the start of each chunk")
    p.add_argument("--fake", action="store_true", help="fake models (tests)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("token", help="create the API token file (token mode)")
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("serve", help="start the API on 127.0.0.1")
    p.add_argument("--no-warm-up", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("openapi", help="write the OpenAPI contract")
    p.add_argument("--output", default="-")
    p.set_defaults(func=cmd_openapi)

    from atlas import evaluation

    evaluation.add_command(sub)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
