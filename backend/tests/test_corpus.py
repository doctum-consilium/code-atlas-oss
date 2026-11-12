"""Corpus selection on small real git repositories created for the test."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas import corpus, secrets
from atlas.config import CorpusSettings
from tests.conftest import make_repo


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/api.git", ("github.com", "acme", "api")),
        ("https://github.com/acme/web", ("github.com", "acme", "web")),
        ("git@github.com:acme/cli.git", ("github.com", "acme", "cli")),
        ("ssh://git@gitlab.com/team/group/tool.git", ("gitlab.com", "team/group", "tool")),
        ("https://user@git.example.org:8443/a/b.git", ("git.example.org", "a", "b")),
        ("/srv/git/local.git", None),
        (None, None),
    ],
)
def test_parse_remote(url: str | None, expected: tuple[str, str, str] | None) -> None:
    assert corpus.parse_remote(url) == expected


def _decide(root: Path, settings: CorpusSettings, forks: dict[str, bool | None]) -> dict[str, str]:
    decisions = corpus.decide_repos(
        corpus.discover((root,)),
        settings,
        lambda _o, n: forks.get(n, False),
        tracked_count=lambda r: len(corpus.list_tracked(r.path)),
    )
    return {d.repo.path.name: d.reason for d in decisions}


def test_any_repository_is_kept_without_owner_list(tmp_path: Path) -> None:
    code = {"a.py": "x = 1\n"}
    make_repo(tmp_path, "api", code, "https://github.com/acme/api.git")
    make_repo(tmp_path, "tool", code, "git@gitlab.com:team/tool.git")
    make_repo(tmp_path, "scratch", code)
    reasons = _decide(tmp_path, CorpusSettings(roots=(tmp_path,)), {})
    assert reasons == {"api": "kept", "tool": "kept", "scratch": "kept"}


def test_rules_in_order(tmp_path: Path) -> None:
    code = {"a.py": "x = 1\n"}
    make_repo(tmp_path, "api", code, "https://github.com/acme/api.git")
    make_repo(tmp_path, "api-copy", code, "https://github.com/acme/api.git")
    make_repo(tmp_path, "scratch", code)
    make_repo(tmp_path, "upstream", code, "https://github.com/bigcorp/engine.git")
    make_repo(tmp_path, "vendored", code, "https://github.com/acme/vendored.git")
    make_repo(tmp_path, "forked", code, "https://github.com/acme/forked.git")
    make_repo(tmp_path, "unknown", code, "https://github.com/acme/unknown.git")
    make_repo(tmp_path, "empty", {}, "https://github.com/acme/empty.git")
    settings = CorpusSettings(
        roots=(tmp_path,),
        owners=("acme",),
        exclude_forks=True,
        exclude={"acme/vendored": "third-party code"},
    )
    reasons = _decide(tmp_path, settings, {"forked": True, "unknown": None})
    assert reasons == {
        "api": "kept",
        "api-copy": "second clone of api",
        "empty": "no tracked file",
        "forked": "fork of another repository",
        "scratch": "owner not listed (no remote)",
        "unknown": "fork status unknown (GitHub unreachable)",
        "upstream": "owner not listed (bigcorp)",
        "vendored": "excluded: third-party code",
    }


def test_fork_check_is_skipped_when_disabled(tmp_path: Path) -> None:
    make_repo(tmp_path, "forked", {"a.py": "x = 1\n"}, "https://github.com/acme/forked.git")
    assert _decide(tmp_path, CorpusSettings(roots=(tmp_path,)), {"forked": True}) == {
        "forked": "kept"
    }


def test_repo_keys() -> None:
    assert corpus.Repo(Path("/x/api"), "github.com", "acme", "api", "u").key == "acme/api"
    assert corpus.Repo(Path("/x/scratch"), None, None, None, None).key == "local/scratch"


@pytest.mark.parametrize(
    ("path", "head", "size", "reason"),
    [
        ("src/app.py", b"x = 1", 10, None),
        ("README.md", b"# title", 10, None),
        (".env.example", b"KEY=", 10, None),
        ("node_modules/x/index.js", b"", 10, "ignored folder"),
        ("app/build/out.js", b"", 10, "ignored folder"),
        (".env", b"", 10, "key or environment file"),
        ("deploy/.env.prod", b"", 10, "key or environment file"),
        ("certs/server.pem", b"", 10, "key or environment file"),
        ("uv.lock", b"", 10, "generated file"),
        ("web/app.min.js", b"", 10, "generated file"),
        ("lib/model.g.dart", b"", 10, "generated file"),
        ("img/logo.png", b"", 10, "file type not indexed"),
        ("data/big.py", b"", 2_000_000, "too large"),
        ("odd.py", b"ab\0cd", 10, "binary"),
    ],
)
def test_skip_reason(path: str, head: bytes, size: int, reason: str | None) -> None:
    assert corpus.skip_reason(path, size, head, 1_000_000) == reason


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/risk.py", ("python", "code")),
        ("tests/test_risk.py", ("python", "test")),
        ("lib/x_test.dart", ("dart", "test")),
        ("web/src/Chat.spec.tsx", ("tsx", "test")),
        ("docs/plan.md", ("markdown", "doc")),
        ("k8s/app.yaml", ("yaml", "config")),
        ("Dockerfile", ("dockerfile", "config")),
        ("photo.jpg", None),
    ],
)
def test_classify(path: str, expected: tuple[str, str] | None) -> None:
    assert corpus.classify(path) == expected


def test_duplicates_kept_on_the_preferred_owner_side(tmp_path: Path) -> None:
    content = {"tool.py": "def tool():\n    return 42\n", "own.py": "x = 1\n"}
    make_repo(tmp_path / "a", "tool", content, "https://github.com/personal/tool.git")
    make_repo(
        tmp_path / "b", "tool", {"tool.py": content["tool.py"]}, "https://github.com/org/tool.git"
    )
    settings = CorpusSettings(roots=(tmp_path / "a", tmp_path / "b"), owners=("org", "personal"))
    report = corpus.build(settings, lambda *_: False)
    assert {(f.repo, f.path) for f in report.files} == {
        ("org/tool", "tool.py"),
        ("personal/tool", "own.py"),
    }
    assert report.skipped["duplicate of a kept file"] == 1
    assert set(report.commits) == {"org/tool", "personal/tool"}


def test_symlinks_and_non_utf8_names_are_not_followed(tmp_path: Path) -> None:
    path = make_repo(tmp_path, "d", {"a.py": "x = 1\n"}, "https://github.com/acme/d")
    (path / "link.py").symlink_to("/etc/hostname")
    (path / "caf\xe9.py".encode("latin-1").decode("utf-8", "surrogateescape")).write_text("y = 2")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    assert [e.path for e in corpus.list_tracked(path)] == ["a.py"]


def test_secret_found_without_its_value(tmp_path: Path) -> None:
    header = "-----BEGIN " + "RSA PRIVATE KEY-----"
    fake_key = f"{header}\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----\n"
    leaking = tmp_path / "config.py"
    leaking.write_text(f'KEY = """{fake_key}"""\n', encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    alerts = secrets.scan_all([("d/config.py", leaking), ("d/clean.py", clean)], processes=2)
    assert {a.path for a in alerts} == {"d/config.py"}
    assert all("MIIB" not in repr(a) for a in alerts)


def test_split_masks_lines_and_excludes_private_keys() -> None:
    alerts = [
        secrets.Alert("d/a.py", "Secret Keyword", 3),
        secrets.Alert("d/a.py", "Basic Auth Credentials", 1),
        secrets.Alert("d/b.py", "Private Key", 2),
        secrets.Alert("d/b.py", "Secret Keyword", 5),
    ]
    excluded, masked = secrets.split(alerts)
    assert excluded == {"d/b.py"}
    assert masked == {"d/a.py": [1, 3]}


def test_mask_replaces_only_the_given_lines() -> None:
    assert secrets.mask("one\ntwo\nthree", [2, 3, 99]) == f"one\n{secrets.MASK}\n{secrets.MASK}"
    assert secrets.mask("one", []) == "one"
