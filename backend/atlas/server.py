"""code-atlas HTTP API (FastAPI), on the loopback interface only.

Every route except ``/healthz`` and ``/v1/public-config`` requires a valid token
(:mod:`atlas.auth`). Around the routes: foreign ``Host`` headers refused (DNS rebinding), CORS
limited to the exact web origins, bounded bodies, per-user rate limits, security headers.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import sql
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atlas import chat, schemas, search, secrets, thermal
from atlas.auth import Identity, Rejected, Verifier
from atlas.config import Settings
from atlas.models import Embedder, Reranker
from atlas.policy import Gatekeeper

log = logging.getLogger("atlas.server")

MAX_BODY_BYTES = 64 * 1024
MAX_FILE_BYTES = 1_000_000
CHAT_CHUNKS = 8


@dataclass
class IndexState:
    """Indexing started from the API (one at a time)."""

    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class Services:
    """Everything the routes need; replaceable in tests."""

    settings: Settings
    connection: Callable[[], AbstractContextManager[psycopg.Connection]]
    embedder: Embedder
    reranker: Reranker | None
    verifier: Verifier
    gatekeeper: Gatekeeper
    start_indexing: Callable[[IndexState], None] | None = None
    model_lock: threading.Lock = field(default_factory=threading.Lock)
    indexing: IndexState = field(default_factory=IndexState)
    _served: tuple[float, set[str] | None] = (0.0, None)

    def served(self) -> set[str] | None:
        """Gateway aliases, read again every 10 minutes."""
        g = self.settings.gateway
        if not g.enabled:
            return None
        read_at, value = self._served
        if time.monotonic() - read_at > 600 or value is None:
            value = chat.served_models(g.url, g.key())
            self._served = (time.monotonic(), value)
        return value


class RateLimiter:
    """One-minute sliding window per (user, usage)."""

    def __init__(self) -> None:
        self._calls: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, subject: str, usage: str, per_minute: int) -> bool:
        """True if the call passes; records it."""
        now = time.monotonic()
        with self._lock:
            calls = self._calls.setdefault((subject, usage), deque())
            while calls and now - calls[0] > 60:
                calls.popleft()
            if len(calls) >= per_minute:
                return False
            calls.append(now)
            return True


class BodyLimit:
    """Refuse (413) a request body larger than ``maximum`` bytes, declared or not."""

    def __init__(self, app: ASGIApp, maximum: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and int(declared or 0) > self.maximum:
            await JSONResponse({"detail": "request too large"}, 413)(scope, receive, send)
            return
        received = 0

        async def read() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum:
                    raise HTTPException(413, "request too large")
            return message

        await self.app(scope, read, send)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-site",
}


def create_app(services: Services, hosts: tuple[str, ...] = ("127.0.0.1", "localhost")) -> FastAPI:
    """Build the application; ``hosts`` = accepted ``Host`` header values (without port)."""
    s = services.settings
    app = FastAPI(
        title="code-atlas",
        version="1.0.0",
        description="Hybrid search and questions over your own code repositories.",
        docs_url=None,
        redoc_url=None,
    )
    limiter = RateLimiter()

    @app.middleware("http")
    async def security(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.web_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(BodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))

    @app.exception_handler(Rejected)
    async def rejected(_request: Request, error: Rejected) -> JSONResponse:
        log.info("access refused (%d): %s", error.status, error.reason)
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else {}
        detail = "not authenticated" if error.status == 401 else "access denied"
        return JSONResponse({"detail": detail}, error.status, headers=headers)

    def identity(authorization: Annotated[str | None, Header()] = None) -> Identity:
        return services.verifier.verify(authorization)

    def limit(who: Identity, usage: str, per_minute: int) -> None:
        if not limiter.allow(who.subject, usage, per_minute):
            raise HTTPException(429, "too many requests, try again in a minute")

    def links() -> dict[str, str]:
        return s.corpus.links

    @app.get("/healthz", response_model=schemas.Health)
    def health() -> schemas.Health:
        return schemas.Health(status="ok")

    @app.get("/v1/public-config", response_model=schemas.PublicConfig)
    def public_config() -> schemas.PublicConfig:
        oidc = None
        if s.auth.mode == "oidc":
            o = s.auth.oidc
            oidc = schemas.OidcPublic(
                issuer=o.issuer, web_client=o.web_client, desktop_client=o.desktop_client
            )
        language = s.language if s.language in ("en", "fr") else "en"
        return schemas.PublicConfig(
            auth_mode="oidc" if s.auth.mode == "oidc" else "token",
            language=language,  # type: ignore[arg-type]
            oidc=oidc,
        )

    @app.get("/v1/me", response_model=schemas.Me)
    def me(who: Identity = Depends(identity)) -> schemas.Me:
        return schemas.Me(subject=who.subject, email=who.email, client=who.client, admin=who.admin)

    @app.get("/v1/repos", response_model=list[schemas.RepoOut])
    def repos(who: Identity = Depends(identity)) -> list[schemas.RepoOut]:
        with services.connection() as c, c.cursor() as cur:
            cur.execute(
                """SELECT r.key, r.commit, r.indexed_at, r.local_only,
                          (SELECT count(*) FROM files f WHERE f.repo = r.key),
                          (SELECT count(*) FROM chunks k WHERE k.repo = r.key)
                   FROM repos r ORDER BY r.key"""
            )
            return [
                schemas.RepoOut(
                    key=key,
                    commit=commit,
                    indexed_at=when.isoformat(),
                    local_only=local,
                    files=nf,
                    chunks=nc,
                )
                for key, commit, when, local, nf, nc in cur.fetchall()
            ]

    @app.get("/v1/facets", response_model=schemas.Facets)
    def facets(who: Identity = Depends(identity)) -> schemas.Facets:
        values: dict[str, list[str]] = {}
        with services.connection() as c, c.cursor() as cur:
            for column in ("repo", "language", "type"):
                cur.execute(
                    sql.SQL("SELECT DISTINCT {} FROM files ORDER BY 1").format(
                        sql.Identifier(column)
                    )
                )
                values[column] = [v for (v,) in cur.fetchall()]
        owners = sorted({r.split("/", 1)[0] for r in values["repo"]})
        return schemas.Facets(
            repos=values["repo"], languages=values["language"], types=values["type"], owners=owners
        )

    def find(
        question: str, filters: schemas.Filters, k: int, mode: search.Mode
    ) -> list[search.Result]:
        f = search.Filters(
            tuple(filters.repos),
            tuple(filters.languages),
            tuple(filters.types),
            tuple(filters.owners),
        )
        with services.connection() as c, services.model_lock:
            return search.search(
                c, services.embedder, services.reranker, question, f, k=k, mode=mode, links=links()
            )

    @app.post("/v1/search", response_model=schemas.SearchResponse)
    def do_search(
        request: schemas.SearchRequest, who: Identity = Depends(identity)
    ) -> schemas.SearchResponse:
        limit(who, "search", s.limits.searches_per_minute)
        start = time.monotonic()
        results = find(request.question, request.filters, request.k, request.mode)
        return schemas.SearchResponse(
            results=[_chunk_out(r) for r in results],
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    @app.get("/v1/chunks/{chunk_id}", response_model=schemas.ChunkOut)
    def chunk(chunk_id: int, who: Identity = Depends(identity)) -> schemas.ChunkOut:
        with services.connection() as c:
            found = search.load_chunk(c, chunk_id, links())
        if found is None:
            raise HTTPException(404, "chunk not found")
        return _chunk_out(found)

    @app.get("/v1/files", response_model=schemas.FileOut)
    def file(
        repo: Annotated[str, Query(max_length=300)],
        path: Annotated[str, Query(max_length=1000)],
        who: Identity = Depends(identity),
    ) -> schemas.FileOut:
        # Only a (repo, path) pair present in the index is served: no free path.
        with services.connection() as c, c.cursor() as cur:
            cur.execute(
                """SELECT r.path, r.host, r.commit, f.language, f.masked_lines FROM files f
                   JOIN repos r ON r.key = f.repo WHERE f.repo = %s AND f.path = %s""",
                (repo, path),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "file not indexed")
        root, host, commit, language, masked = row
        absolute = (Path(root) / path).resolve()
        if not absolute.is_relative_to(Path(root).resolve()) or not absolute.is_file():
            raise HTTPException(404, "file not indexed")
        if absolute.stat().st_size > MAX_FILE_BYTES:
            raise HTTPException(413, "file too large to display")
        content = secrets.mask(absolute.read_text(encoding="utf-8", errors="replace"), masked)
        url = search.source_link(links(), host, repo, commit, path, 1, 1)
        return schemas.FileOut(
            repo=repo,
            path=path,
            language=language,
            content=content,
            masked_lines=list(masked),
            url=url.split("#", 1)[0] if url else None,
        )

    @app.get("/v1/models", response_model=schemas.Models)
    def models(who: Identity = Depends(identity)) -> schemas.Models:
        installed = chat.installed_local_models(s.models.local_url)
        served = services.served()
        return schemas.Models(
            local=[
                schemas.LocalModel(
                    name=n, installed=n in installed, default=n == s.models.local_default
                )
                for n in s.models.local
            ],
            gateway=[schemas.RemoteModel(**v.__dict__) for v in services.gatekeeper.all(served)]
            if s.gateway.enabled
            else [],
            gateway_enabled=s.gateway.enabled and s.gateway.key() is not None,
        )

    @app.post("/v1/chat")
    def ask(
        request: schemas.QuestionRequest, who: Identity = Depends(identity)
    ) -> StreamingResponse:
        limit(who, "question", s.limits.questions_per_minute)
        history: list[tuple[str, str]] = []
        if request.conversation_id:
            history = _history(services, who, request.conversation_id)
        chunks = find(request.question, request.filters, CHAT_CHUNKS, "hybrid")
        model = request.model or s.models.local_default
        try:
            target = chat.choose_target(
                request.mode,
                model,
                chunks,
                local_models=s.models.local,
                local_url=s.models.local_url,
                gatekeeper=services.gatekeeper,
                gateway_enabled=s.gateway.enabled,
                gateway_url=s.gateway.url,
                gateway_key=s.gateway.key(),
                served=services.served() if request.mode == "gateway" else None,
            )
        except chat.Refused as refused:
            raise HTTPException(409, refused.reason) from refused
        conversation_id = request.conversation_id or str(uuid.uuid4())
        messages = chat.build_messages(request.question, chunks, history, s.language)
        return StreamingResponse(
            _stream(
                services,
                who,
                conversation_id,
                request.question,
                target,
                messages,
                chunks,
                new=request.conversation_id is None,
            ),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/v1/conversations", response_model=list[schemas.ConversationSummary])
    def conversations(who: Identity = Depends(identity)) -> list[schemas.ConversationSummary]:
        with services.connection() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, title, created_at FROM conversations WHERE subject = %s "
                "ORDER BY created_at DESC LIMIT 200",
                (who.subject,),
            )
            return [
                schemas.ConversationSummary(id=str(i), title=t, created_at=w.isoformat())
                for i, t, w in cur.fetchall()
            ]

    @app.get("/v1/conversations/{conversation_id}", response_model=schemas.Conversation)
    def conversation(
        conversation_id: uuid.UUID, who: Identity = Depends(identity)
    ) -> schemas.Conversation:
        with services.connection() as c, c.cursor() as cur:
            cur.execute(
                "SELECT title, created_at FROM conversations WHERE id = %s AND subject = %s",
                (conversation_id, who.subject),
            )
            head = cur.fetchone()
            if head is None:
                raise HTTPException(404, "conversation not found")
            cur.execute(
                "SELECT role, content, model, citations, created_at FROM messages "
                "WHERE conversation_id = %s ORDER BY id",
                (conversation_id,),
            )
            messages = [
                schemas.Message(
                    role=role,
                    content=content,
                    model=m,
                    citations=[schemas.Citation(**x) for x in cits],
                    created_at=w.isoformat(),
                )
                for role, content, m, cits, w in cur.fetchall()
            ]
        return schemas.Conversation(
            id=str(conversation_id),
            title=head[0],
            created_at=head[1].isoformat(),
            messages=messages,
        )

    @app.delete("/v1/conversations/{conversation_id}", status_code=204)
    def delete(conversation_id: uuid.UUID, who: Identity = Depends(identity)) -> Response:
        services.verifier.require_admin(who)
        with services.connection() as c, c.cursor() as cur:
            cur.execute(
                "DELETE FROM conversations WHERE id = %s AND subject = %s",
                (conversation_id, who.subject),
            )
            deleted = cur.rowcount
            c.commit()
        if not deleted:
            raise HTTPException(404, "conversation not found")
        return Response(status_code=204)

    @app.get("/v1/index", response_model=schemas.IndexStatus)
    def index_status(who: Identity = Depends(identity)) -> schemas.IndexStatus:
        e = services.indexing
        return schemas.IndexStatus(
            running=e.running, started_at=e.started_at, finished_at=e.finished_at, message=e.message
        )

    @app.post("/v1/index", response_model=schemas.IndexStatus, status_code=202)
    def start_index(who: Identity = Depends(identity)) -> schemas.IndexStatus:
        services.verifier.require_admin(who)
        e = services.indexing
        if services.start_indexing is None:
            raise HTTPException(503, "indexing unavailable in this mode")
        with e.lock:
            if e.running:
                raise HTTPException(409, "an indexing run is already in progress")
            e.running, e.started_at, e.finished_at = True, _now(), None
            e.message = "selecting the corpus…"
        threading.Thread(target=services.start_indexing, args=(e,), daemon=True).start()
        return schemas.IndexStatus(running=True, started_at=e.started_at, message=e.message)

    return app


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _chunk_out(r: search.Result) -> schemas.ChunkOut:
    return schemas.ChunkOut(
        id=r.id,
        repo=r.repo,
        path=r.path,
        language=r.language,
        type=r.type,
        kind=r.kind,
        symbol=r.symbol,
        line_start=r.line_start,
        line_end=r.line_end,
        text=r.text,
        url=r.url,
        score=r.score,
        local_only=r.local_only,
        ranks=r.ranks,
    )


def _history(services: Services, who: Identity, conversation_id: str) -> list[tuple[str, str]]:
    with services.connection() as c, c.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND subject = %s",
            (conversation_id, who.subject),
        )
        if cur.fetchone() is None:
            raise HTTPException(404, "conversation not found")
        cur.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        )
        return [(role, content) for role, content in cur.fetchall()]


def _event(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream(
    services: Services,
    who: Identity,
    conversation_id: str,
    question: str,
    target: chat.Target,
    messages: list[dict[str, str]],
    chunks: list[search.Result],
    *,
    new: bool,
) -> Iterator[str]:
    yield _event(
        "chunks",
        {
            "conversation_id": conversation_id,
            "model": target.model,
            "provider": target.provider,
            "remote": target.mode == "gateway",
            "chunks": [_chunk_out(c).model_dump() for c in chunks],
        },
    )
    answer: list[str] = []
    try:
        if target.mode == "local":
            thermal.GUARD.wait()  # the local model heats the GPU: pause rather than crash
        for text in chat.stream(target, messages):
            answer.append(text)
            yield _event("token", {"text": text})
    except chat.Refused as refused:
        yield _event("error", {"reason": refused.reason})
        return
    full = "".join(answer)
    valid, invalid = chat.citations(full, len(chunks))
    cited = [
        schemas.Citation(
            n=n,
            chunk_id=chunks[n - 1].id,
            repo=chunks[n - 1].repo,
            path=chunks[n - 1].path,
            line_start=chunks[n - 1].line_start,
            line_end=chunks[n - 1].line_end,
            url=chunks[n - 1].url,
        ).model_dump()
        for n in valid
    ]
    with services.connection() as c, c.cursor() as cur:
        if new:
            cur.execute(
                "INSERT INTO conversations (id, subject, title) VALUES (%s, %s, %s)",
                (conversation_id, who.subject, question[:80]),
            )
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
            (conversation_id, question),
        )
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content, model, citations) "
            "VALUES (%s, 'assistant', %s, %s, %s)",
            (conversation_id, full, target.model, json.dumps(cited)),
        )
        c.commit()
    yield _event(
        "done",
        {"conversation_id": conversation_id, "citations": cited, "invalid_citations": invalid},
    )


# ---------------------------------------------------------------------------- start-up


def real_services(settings: Settings) -> Services:
    """Services of this machine: database, local models, verifier, policy."""
    from atlas import cli, db, indexer
    from atlas.auth import verifier_for
    from atlas.models import (
        CrossEncoderReranker,
        FakeEmbedder,
        FakeReranker,
        SentenceTransformerEmbedder,
    )
    from atlas.policy import Policy

    pool = db.pool(settings.database.dsn())
    with pool.connection() as c:
        db.migrate(c, settings.models.dimension)

    @contextmanager
    def connection() -> Iterator[psycopg.Connection]:
        with pool.connection() as c:
            yield c

    m = settings.models
    # Fake models: end-to-end tests only (CI without GPU), never by default.
    fake = os.environ.get("CODE_ATLAS_MODELS") == "fake"
    embedder: Embedder = (
        FakeEmbedder(m.dimension)
        if fake
        else SentenceTransformerEmbedder(m.embedder, m.dimension, m.query_prompt)
    )
    reranker: Reranker | None = (
        FakeReranker() if fake else CrossEncoderReranker(m.reranker) if m.reranker else None
    )

    def run_indexing(state: IndexState) -> None:
        try:
            manifest, _text = cli.build_manifest(settings)
            state.message = "updating the index…"
            with connection() as c:
                summary = indexer.index(manifest, c, embedder)
            state.message = (
                f"{summary.files_read} files read, {summary.files_removed} removed, "
                f"{summary.chunks_added} chunks in {summary.duration_s:.0f} s"
            )
        except Exception as error:
            log.exception("indexing failed")
            state.message = f"failed: {type(error).__name__}"
        finally:
            state.running, state.finished_at = False, _now()

    return Services(
        settings=settings,
        connection=connection,
        embedder=embedder,
        reranker=reranker,
        verifier=verifier_for(settings.auth),
        gatekeeper=Gatekeeper(Policy.load(Path(settings.gateway.policy_file).expanduser())),
        start_indexing=run_indexing,
    )


def warm_up(services: Services) -> None:
    """Load the models before the first question."""
    with services.model_lock:
        services.embedder.query("warm-up")
        if services.reranker:
            services.reranker.score("warm-up", ["warm-up"])
    log.info("models loaded")
