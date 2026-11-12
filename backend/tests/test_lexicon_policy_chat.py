"""Lexical text, remote-model policy, chat routing, prompt, citations and streaming."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from atlas import chat, lexicon, policy
from atlas.config import REPO_ROOT
from atlas.search import Result

POLICY = REPO_ROOT / "config" / "policy.example.toml"


# ------------------------------------------------------------------ lexicon


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("canReceiveShare", ["canreceiveshare", "can", "receive", "share"]),
        (
            "_can_receive_the_share",
            ["_can_receive_the_share", "can", "receive", "the", "share", "canreceivetheshare"],
        ),
        ("HTTPServer", ["httpserver", "http", "server"]),
        ("réglage", ["réglage", "reglage"]),
        ("x", ["x"]),
    ],
)
def test_variants(token: str, expected: list[str]) -> None:
    assert lexicon.variants(token) == expected


def test_question_and_code_meet() -> None:
    code = set(lexicon.lexical_text("def can_receive_shared_feed(account):").split())
    question = set(lexicon.lexical_query("where can we receive the shared feed?").split())
    assert {"receive", "shared", "feed"} <= code & question
    assert "the" not in question and "where" not in question


def test_empty_query_when_only_stop_words() -> None:
    assert lexicon.lexical_query("where is the ?") == ""
    assert lexicon.lexical_text(None, "", "Hello") == "hello"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("what does _can_receive_shared_feed do?", ["_can_receive_shared_feed"]),
        ("explain CrossEncoderReranker.score", ["CrossEncoderReranker"]),
        ("where are rrf_fuse and loadConfig", ["rrf_fuse", "loadConfig"]),
        ("how does search work", []),
    ],
)
def test_identifiers(question: str, expected: list[str]) -> None:
    assert lexicon.identifiers(question) == expected


# ------------------------------------------------------------------ policy


def _keeper(mode: str | None, today: dt.date = dt.date(2026, 11, 13)) -> policy.Gatekeeper:
    raw = POLICY.read_text() + '\n[[models]]\nalias = "bedrock-coder"\nprovider = "bedrock"\n'
    path = Path(__file__).parent / "_policy.toml"
    path.write_text(raw)
    try:
        return policy.Gatekeeper(policy.Policy.load(path), lambda _r: mode, lambda: today)
    finally:
        path.unlink()


def test_alias_outside_the_list_is_refused() -> None:
    verdict = _keeper("none").judge("gpt-unknown")
    assert not verdict.allowed and verdict.reason == "alias not in the policy file"


def test_date_checked_provider_allowed_then_warned() -> None:
    assert _keeper(None).judge("scw-qwen3-coder-30b").allowed
    old = _keeper(None, dt.date(2027, 6, 1)).judge("scw-qwen3-coder-30b")
    assert old.allowed and old.warning and "read it again" in old.warning


@pytest.mark.parametrize("mode", ["default", "aws_review", "inherit", None])
def test_bedrock_refused_unless_mode_none(mode: str | None) -> None:
    verdict = _keeper(mode).judge("bedrock-coder")
    assert not verdict.allowed and "'none'" in verdict.reason


def test_bedrock_allowed_in_mode_none_with_todays_date() -> None:
    verdict = _keeper("none").judge("bedrock-coder")
    assert verdict.allowed and verdict.verified_on == "2026-11-13"


def test_alias_not_served_is_refused() -> None:
    assert not _keeper("none").judge("scw-qwen3-coder-30b", served={"other"}).allowed


def test_aws_mode_read_once_then_cached() -> None:
    reads: list[str] = []

    def reader(region: str) -> str:
        reads.append(region)
        return "none"

    raw = policy.Policy(
        {"b": policy.Provider("b", "aws-bedrock", dt.date(2026, 1, 1), "", "", "eu-west-1")},
        {"m": "b"},
    )
    keeper = policy.Gatekeeper(raw, reader)
    keeper.all()
    keeper.all()
    assert reads == ["eu-west-1"]
    keeper.forget()
    keeper.judge("m")
    assert len(reads) == 2


def test_policy_files(tmp_path: Path) -> None:
    assert policy.Policy.load(tmp_path / "missing.toml").models == {}
    bad = tmp_path / "p.toml"
    bad.write_text('[providers]\n[[models]]\nalias = "x"\nprovider = "nope"\n')
    with pytest.raises(ValueError, match="without a policy"):
        policy.Policy.load(bad)
    odd = tmp_path / "odd.toml"
    odd.write_text(
        '[providers.p]\ncheck = "magic"\nverified_on = 2026-01-01\n'
        '[[models]]\nalias = "m"\nprovider = "p"\n'
    )
    assert "unknown check" in policy.Gatekeeper(policy.Policy.load(odd)).judge("m").reason


def test_read_bedrock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout="none\n"),
    )
    assert policy.read_bedrock_mode("eu-west-1") == "none"

    def broken(*_a: object, **_k: object) -> None:
        raise OSError("no aws")

    monkeypatch.setattr(policy.subprocess, "run", broken)
    assert policy.read_bedrock_mode("eu-west-1") is None


# ------------------------------------------------------------------ chat


def _chunk(repo: str = "acme/api", local: bool = False) -> Result:
    return Result(
        1,
        repo,
        "app/x.py",
        "python",
        "code",
        "function",
        "f",
        3,
        9,
        "def f(): ...",
        "https://example.org/x",
        local,
    )


def _choose(
    mode: chat.Mode,
    model: str,
    chunks: list[Result],
    key: str | None = "k",
    keeper: policy.Gatekeeper | None = None,
    enabled: bool = True,
) -> chat.Target:
    return chat.choose_target(
        mode,
        model,
        chunks,
        local_models=["coder:14b"],
        local_url="http://127.0.0.1:11434",
        gatekeeper=keeper or _keeper("none"),
        gateway_enabled=enabled,
        gateway_url="https://llm.example.org",
        gateway_key=key,
        served=None,
    )


def test_local_without_key() -> None:
    target = _choose("local", "coder:14b", [_chunk()])
    assert target.url == "http://127.0.0.1:11434/v1" and target.key is None


@pytest.mark.parametrize(
    ("mode", "model", "chunks", "kwargs", "message"),
    [
        ("local", "pirate", [], {}, "unknown local model"),
        ("gateway", "scw-qwen3-coder-30b", [], {"enabled": False}, "disabled"),
        (
            "gateway",
            "scw-qwen3-coder-30b",
            [_chunk("acme/secret", local=True)],
            {},
            "never leave this machine",
        ),
        ("gateway", "gpt-unknown", [_chunk()], {}, "not in the policy file"),
        ("gateway", "scw-qwen3-coder-30b", [], {"key": None}, "no gateway key"),
    ],
)
def test_refusals(
    mode: chat.Mode, model: str, chunks: list[Result], kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(chat.Refused, match=message):
        _choose(mode, model, chunks, **kwargs)  # type: ignore[arg-type]


def test_gateway_accepted() -> None:
    target = _choose("gateway", "scw-qwen3-coder-30b", [_chunk()])
    assert target.provider == "scaleway" and target.url == "https://llm.example.org/v1"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
def test_messages_fence_chunks_and_keep_4_exchanges(language: str) -> None:
    history = [("user", f"q{i}") for i in range(6)]
    messages = chat.build_messages("Why?", [_chunk()], history, language)
    system = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert "DATA" in system or "DONNÉES" in system  # the injection guard, in both languages
    assert len(messages) == 1 + 4 + 1
    last = messages[-1]["content"]
    assert '[1] <chunk n="1" repo="acme/api" path="app/x.py" lines="3-9"' in last
    assert "Question: Why?" in last


def test_citations_valid_and_out_of_range() -> None:
    assert chat.citations("A [1], B [3][1], C [9]", 3) == ([1, 3], [9])


def _client(lines: list[str], status: int = 200) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(status, text="\n".join(lines))

    return httpx.Client(transport=httpx.MockTransport(answer))


def test_stream_reads_openai_chunks() -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        ": comment",
        "data: not json",
        'data: {"choices":[{"delta":{}}]}',
        'data: {"choices":[{"delta":{"content":"lo [1]"}}]}',
        "data: [DONE]",
    ]
    target = chat.Target("local", "m", "http://x/v1", None, "local")
    assert "".join(chat.stream(target, [], _client(lines))) == "Hello [1]"


def test_stream_errors() -> None:
    target = chat.Target("gateway", "m", "http://x/v1", "k", "p")
    with pytest.raises(chat.Refused, match="500"):
        list(chat.stream(target, [], _client([], status=500)))

    def down(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(chat.Refused, match="unreachable"):
        list(chat.stream(target, [], httpx.Client(transport=httpx.MockTransport(down))))


def test_installed_and_served_models() -> None:
    def ollama(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "coder:14b"}]})
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": [{"id": "scw-x"}]})

    client = httpx.Client(transport=httpx.MockTransport(ollama))
    assert chat.installed_local_models("http://o", client) == {"coder:14b"}
    assert chat.served_models("http://p", "k", client) == {"scw-x"}
    assert chat.served_models("http://p", None, client) is None

    def openai_only(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": [{"id": "llama"}]})

    client = httpx.Client(transport=httpx.MockTransport(openai_only))
    assert chat.installed_local_models("http://o", client) == {"llama"}

    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(503)))
    assert chat.installed_local_models("http://o", client) == set()
    assert chat.served_models("http://p", "k", client) is None
