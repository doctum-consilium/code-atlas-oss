"""The API end to end: front door, hardening, routes, chat stream, history."""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from atlas import chat, indexer, policy, server
from atlas.auth import OidcVerifier, TokenVerifier, create_token_file
from atlas.config import AuthSettings, GatewaySettings, LimitSettings, Settings
from atlas.models import FakeEmbedder, FakeReranker
from tests.conftest import SAMPLE_FILES, make_repo, manifest_for
from tests.test_auth import SETTINGS as OIDC
from tests.test_auth import jwks, token

ORIGIN = "http://127.0.0.1:5173"
ADMIN = {"code-atlas": {"roles": ["user", "admin"]}}
POLICY = policy.Policy(
    {"scw": policy.Provider("scw", "date", dt.date(2026, 11, 12), "s", "zero retention")},
    {"scw-coder": "scw"},
)


def _services(connection: psycopg.Connection | None, **others: Any) -> server.Services:
    settings = Settings(
        web_origins=(ORIGIN,),
        auth=AuthSettings(mode="oidc", oidc=OIDC),
        limits=others.pop("limits", LimitSettings()),
        gateway=others.pop("gateway", GatewaySettings()),
        language=others.pop("language", "en"),
    )

    @contextmanager
    def provide() -> Iterator[psycopg.Connection]:
        if connection is None:
            raise RuntimeError("no database")
        yield connection

    return server.Services(
        settings,
        provide,
        FakeEmbedder(),
        FakeReranker(),
        others.pop("verifier", OidcVerifier(OIDC, lambda _u: jwks(), jwks_url="u")),
        policy.Gatekeeper(POLICY, lambda _r: "none", lambda: dt.date(2026, 11, 13)),
        **others,
    )


def _client(services: server.Services) -> TestClient:
    return TestClient(server.create_app(services, hosts=("testserver", "127.0.0.1")))


def _auth(**changes: Any) -> dict[str, str]:
    return {"Authorization": token(**changes)}


# ------------------------------------------------------------------ without database


def test_health_and_public_config_without_token() -> None:
    client = _client(_services(None, language="fr"))
    response = client.get("/healthz")
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    config = client.get("/v1/public-config").json()
    assert config == {
        "auth_mode": "oidc",
        "language": "fr",
        "oidc": {
            "issuer": OIDC.issuer,
            "web_client": "code-atlas-web",
            "desktop_client": "code-atlas-desktop",
        },
    }


def test_public_config_in_token_mode(tmp_path: Path) -> None:
    services = _services(None, verifier=TokenVerifier(str(tmp_path / "t")))
    services.settings = Settings(auth=AuthSettings(mode="token"), language="xx")
    assert _client(services).get("/v1/public-config").json() == {
        "auth_mode": "token",
        "language": "en",
        "oidc": None,
    }


def test_token_mode_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "api-token"
    create_token_file(path)
    client = _client(_services(None, verifier=TokenVerifier(str(path))))
    assert client.get("/v1/me").status_code == 401
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {path.read_text().strip()}"})
    assert me.json() == {"subject": "local", "email": "", "client": "token", "admin": True}


def test_foreign_host_refused() -> None:
    assert (
        _client(_services(None)).get("/healthz", headers={"Host": "evil.example"}).status_code
        == 400
    )


@pytest.mark.parametrize("route", ["/v1/me", "/v1/repos", "/v1/models", "/v1/conversations"])
def test_routes_closed_without_token(route: str) -> None:
    response = _client(_services(None)).get(route)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "not authenticated"}


def test_other_client_refused_without_detail() -> None:
    response = _client(_services(None)).get("/v1/me", headers=_auth(azp="another-app"))
    assert response.status_code == 403 and response.json() == {"detail": "access denied"}


def test_cors_only_for_the_web_front() -> None:
    client = _client(_services(None))
    ok = client.options(
        "/v1/search",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    refused = client.options(
        "/v1/search",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in refused.headers


def test_bodies_bounded_and_unknown_fields_refused() -> None:
    client = _client(_services(None))
    huge = client.post(
        "/v1/search",
        headers=_auth() | {"Content-Type": "application/json"},
        content=b'{"question": "' + b"x" * 70_000 + b'"}',
    )
    assert huge.status_code == 413
    assert (
        client.post("/v1/search", headers=_auth(), json={"question": "x", "pirate": 1}).status_code
        == 422
    )
    assert (
        client.post("/v1/search", headers=_auth(), json={"question": "x" * 4001}).status_code == 422
    )


def test_index_needs_recent_admin() -> None:
    started: list[server.IndexState] = []
    client = _client(_services(None, start_indexing=started.append))
    assert client.post("/v1/index", headers=_auth()).status_code == 403
    old = int(time.time()) - 3600
    assert (
        client.post("/v1/index", headers=_auth(resource_access=ADMIN, auth_time=old)).status_code
        == 403
    )
    response = client.post("/v1/index", headers=_auth(resource_access=ADMIN))
    assert response.status_code == 202 and response.json()["running"] is True
    time.sleep(0.05)
    assert len(started) == 1
    assert client.post("/v1/index", headers=_auth(resource_access=ADMIN)).status_code == 409
    assert client.get("/v1/index", headers=_auth()).json()["running"] is True
    assert (
        _client(_services(None)).post("/v1/index", headers=_auth(resource_access=ADMIN)).status_code
        == 503
    )


def test_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat, "installed_local_models", lambda _u: {"qwen2.5-coder:14b"})
    monkeypatch.setattr(chat, "served_models", lambda _u, _k: {"scw-coder"})
    monkeypatch.setenv("CODE_ATLAS_GATEWAY_KEY", "test-key")
    gateway = GatewaySettings(enabled=True, url="https://llm.example.org")
    body = _client(_services(None, gateway=gateway)).get("/v1/models", headers=_auth()).json()
    assert body["gateway_enabled"] is True
    assert [m["name"] for m in body["local"] if m["installed"]] == ["qwen2.5-coder:14b"]
    assert {m["alias"] for m in body["gateway"] if m["allowed"]} == {"scw-coder"}
    assert "test-key" not in json.dumps(body)
    disabled = _client(_services(None)).get("/v1/models", headers=_auth()).json()
    assert disabled["gateway"] == [] and disabled["gateway_enabled"] is False


def test_rate_limiter() -> None:
    limiter = server.RateLimiter()
    assert [limiter.allow("s", "q", 2) for _ in range(3)] == [True, True, False]
    assert limiter.allow("other", "q", 2)


# ------------------------------------------------------------------ with database


@pytest.fixture
def indexed_client(connection: psycopg.Connection, tmp_path: Path) -> tuple[TestClient, Path]:
    repo = make_repo(tmp_path, "sample", SAMPLE_FILES)
    indexer.index(manifest_for(repo, "acme/sample", SAMPLE_FILES), connection, FakeEmbedder())
    return _client(_services(connection)), repo


@pytest.mark.db
def test_repos_facets_search_chunk(indexed_client: tuple[TestClient, Path]) -> None:
    client, _ = indexed_client
    repos = client.get("/v1/repos", headers=_auth()).json()
    assert repos[0]["key"] == "acme/sample" and repos[0]["files"] == 3
    facets = client.get("/v1/facets", headers=_auth()).json()
    assert facets["owners"] == ["acme"] and "python" in facets["languages"]
    found = client.post(
        "/v1/search", headers=_auth(), json={"question": "can_receive_shared_feed", "k": 3}
    ).json()
    first = found["results"][0]
    assert first["symbol"] == "can_receive_shared_feed"
    assert first["url"].startswith("https://github.com/acme/sample/blob/abc123/")
    chunk = client.get(f"/v1/chunks/{first['id']}", headers=_auth()).json()
    assert chunk["text"].startswith("def can_receive_shared_feed")
    assert client.get("/v1/chunks/999999", headers=_auth()).status_code == 404


@pytest.mark.db
def test_search_rate_limited(connection: psycopg.Connection) -> None:
    client = _client(_services(connection, limits=LimitSettings(searches_per_minute=2)))
    codes = [
        client.post("/v1/search", headers=_auth(), json={"question": "x"}).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


@pytest.mark.db
def test_file_only_if_indexed(indexed_client: tuple[TestClient, Path]) -> None:
    client, repo = indexed_client
    (repo / "secret.txt").write_text("outside the corpus", encoding="utf-8")
    ok = client.get(
        "/v1/files", headers=_auth(), params={"repo": "acme/sample", "path": "app/sharing.py"}
    )
    assert ok.status_code == 200 and "can_receive_shared_feed" in ok.json()["content"]
    assert ok.json()["url"] == "https://github.com/acme/sample/blob/abc123/app/sharing.py"
    for path in ("secret.txt", "../sample/secret.txt", "/etc/passwd", "app/../secret.txt"):
        response = client.get(
            "/v1/files", headers=_auth(), params={"repo": "acme/sample", "path": path}
        )
        assert response.status_code == 404, path


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        name = block.split("\n")[0].removeprefix("event: ")
        out.append((name, json.loads(block.split("\n")[1].removeprefix("data: "))))
    return out


@pytest.mark.db
def test_chat_streams_cites_and_keeps_history(
    indexed_client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = indexed_client
    targets: list[chat.Target] = []

    def fake_model(target: chat.Target, messages: list[dict[str, str]]) -> Iterator[str]:
        targets.append(target)
        assert "can_receive_shared_feed" in messages[-1]["content"]
        yield "Only the owner receives the feed [1]"
        yield ", see also [42]."

    monkeypatch.setattr(chat, "stream", fake_model)
    response = client.post(
        "/v1/chat",
        headers=_auth(),
        json={"question": "who receives the shared feed? can_receive_shared_feed"},
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [n for n, _d in events] == ["chunks", "token", "token", "done"]
    assert events[0][1]["remote"] is False and targets[0].mode == "local"
    done = events[-1][1]
    assert [c["n"] for c in done["citations"]] == [1] and done["invalid_citations"] == [42]

    assert len(client.get("/v1/conversations", headers=_auth()).json()) == 1
    cid = done["conversation_id"]
    detail = client.get(f"/v1/conversations/{cid}", headers=_auth()).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    follow_up = client.post(
        "/v1/chat", headers=_auth(), json={"question": "and then?", "conversation_id": cid}
    )
    assert _events(follow_up.text)[-1][0] == "done"
    assert len(client.get(f"/v1/conversations/{cid}", headers=_auth()).json()["messages"]) == 4

    other = _auth(sub="someone-else")
    assert client.get(f"/v1/conversations/{cid}", headers=other).status_code == 404
    assert client.delete(f"/v1/conversations/{cid}", headers=_auth()).status_code == 403
    assert (
        client.delete(f"/v1/conversations/{cid}", headers=_auth(resource_access=ADMIN)).status_code
        == 204
    )
    assert client.get("/v1/conversations", headers=_auth()).json() == []


@pytest.mark.db
def test_chat_refuses_gateway_outside_policy(indexed_client: tuple[TestClient, Path]) -> None:
    client, _ = indexed_client
    response = client.post(
        "/v1/chat",
        headers=_auth(),
        json={"question": "x", "mode": "gateway", "model": "gpt-unknown"},
    )
    assert response.status_code == 409 and "disabled" in response.json()["detail"]


@pytest.mark.db
def test_chat_reports_a_model_failure(
    indexed_client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = indexed_client

    def broken(_t: chat.Target, _m: list[dict[str, str]]) -> Iterator[str]:
        raise chat.Refused("model unreachable (ConnectError)")
        yield ""  # pragma: no cover

    monkeypatch.setattr(chat, "stream", broken)
    events = _events(client.post("/v1/chat", headers=_auth(), json={"question": "x"}).text)
    assert events[-1] == ("error", {"reason": "model unreachable (ConnectError)"})


@pytest.mark.db
def test_unknown_conversation(indexed_client: tuple[TestClient, Path]) -> None:
    client, _ = indexed_client
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (
        client.post(
            "/v1/chat", headers=_auth(), json={"question": "x", "conversation_id": unknown}
        ).status_code
        == 404
    )
    assert client.get(f"/v1/conversations/{unknown}", headers=_auth()).status_code == 404
    assert (
        client.delete(
            f"/v1/conversations/{unknown}", headers=_auth(resource_access=ADMIN)
        ).status_code
        == 404
    )
