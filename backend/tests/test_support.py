"""Settings, thermal guard, fork cache, evaluation, the ``atlas`` commands and the contract."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import psycopg
import pytest
import yaml

from atlas import cli, evaluation, forks, thermal
from atlas.config import REPO_ROOT, Settings
from atlas.search import Result
from tests.conftest import SAMPLE_FILES, make_repo

EXAMPLE = REPO_ROOT / "config" / "config.example.toml"


# ------------------------------------------------------------------ settings


def test_example_settings_load() -> None:
    s = Settings.load(EXAMPLE)
    assert (s.host, s.port, s.auth.mode, s.models.dimension) == ("127.0.0.1", 8790, "token", 1024)
    assert s.auth.oidc.clients == ("code-atlas-web", "code-atlas-desktop")
    assert s.corpus.roots[0].name == "code" and "github.com" in s.corpus.links
    assert s.gateway.enabled is False


def test_settings_lookup_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "c.toml"
    custom.write_text(
        'language = "fr"\n[corpus]\nroots = ["/srv/code"]\n'
        '[corpus.links]\n"git.example.org" = "https://x/{repo}"\n'
    )
    monkeypatch.setenv("CODE_ATLAS_CONFIG", str(custom))
    s = Settings.load()
    assert s.language == "fr" and s.corpus.roots == (Path("/srv/code"),)
    assert {"github.com", "git.example.org"} <= set(s.corpus.links)
    custom.write_text("[server]\nport = 1\n[thermal]\ntypo = 1\n")
    with pytest.raises(TypeError):
        Settings.load()
    monkeypatch.setenv("CODE_ATLAS_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(SystemExit, match="No settings file"):
        Settings.load()


def test_secret_files_are_read_not_stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    password = tmp_path / "pw"
    password.write_text("s3cret\n")
    s = Settings.from_dict(
        {
            "database": {"password_file": str(password)},
            "gateway": {"key_file": str(tmp_path / "missing")},
        }
    )
    monkeypatch.delenv("CODE_ATLAS_DSN", raising=False)
    monkeypatch.delenv("CODE_ATLAS_GATEWAY_KEY", raising=False)
    assert "password=s3cret" in s.database.dsn()
    assert "s3cret" not in repr(s)
    assert s.gateway.key() is None
    monkeypatch.setenv("CODE_ATLAS_DSN", "host=x")
    assert s.database.dsn() == "host=x"


# ------------------------------------------------------------------ thermal guard


def test_cool_machine_does_not_pause() -> None:
    sleeps: list[float] = []
    guard = thermal.Guard(
        gpu=lambda: 60.0, cpu=lambda: 70.0, sleep=sleeps.append, notify=lambda _m: None
    )
    guard.wait()
    assert sleeps == [] and guard.pauses == 0


def test_hot_machine_waits_with_hysteresis() -> None:
    temperatures = iter([82.0, 81.0, 75.0, 71.0])  # 75 > 80 - 8: still waiting
    messages: list[str] = []
    sleeps: list[float] = []
    guard = thermal.Guard(
        gpu=lambda: next(temperatures),
        cpu=lambda: None,
        sleep=sleeps.append,
        notify=messages.append,
    )
    guard.wait(pause_s=1)
    assert sleeps == [1, 1] and guard.pauses == 1
    assert messages[0].startswith("Thermal pause: GPU at 82 °C")


def test_hot_cpu_bounded_wait_and_disabled_guard() -> None:
    guard = thermal.Guard(
        gpu=lambda: None, cpu=lambda: 95.0, sleep=lambda _s: None, notify=lambda _m: None
    )
    guard.wait(pause_s=10, max_s=30)
    assert guard.pauses == 1
    off = thermal.Guard(enabled=False, gpu=lambda: 99.0)
    off.wait()
    assert off.pauses == 0
    thermal.configure(True, 70, 80)
    assert (thermal.GUARD.gpu_max_c, thermal.GUARD.cpu_max_c) == (70, 80)
    thermal.configure(True, 80, 88)


def test_unreadable_sensors_block_nothing(tmp_path: Path) -> None:
    assert thermal.read_cpu(tmp_path) is None
    zone = tmp_path / "thermal_zone0"
    zone.mkdir()
    (zone / "type").write_text("x86_pkg_temp\n")
    (zone / "temp").write_text("61000\n")
    other = tmp_path / "thermal_zone1"
    other.mkdir()
    (other / "type").write_text("acpitz\n")
    (other / "temp").write_text("not a number\n")
    assert thermal.read_cpu(tmp_path) == 61.0
    value = thermal.read_gpu()
    assert value is None or 0 < value < 120


# ------------------------------------------------------------------ forks and evaluation


def test_fork_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_gh(command: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        out = {"repos/o/copy": "true\n", "repos/o/own": "false\n"}.get(command[2], "")
        return subprocess.CompletedProcess(command, 0 if out else 1, stdout=out)

    monkeypatch.setattr(forks.subprocess, "run", fake_gh)
    cache = tmp_path / "forks.json"
    source = forks.GitHubForks(cache)
    assert (source("o", "copy"), source("o", "own"), source("o", "missing")) == (True, False, None)
    source.save()
    assert set(json.loads(cache.read_text())) == {"o/copy", "o/own"}
    assert forks.GitHubForks(cache)("o", "copy") is True and len(calls) == 3
    forks.GitHubForks(cache, refresh=True)("o", "copy")
    assert len(calls) == 4
    cache.write_text("not json")
    assert forks.GitHubForks(cache)._entries == {}


def _r(repo: str, path: str) -> Result:
    return Result(0, repo, path, "python", "code", "function", None, 1, 2, "", None, False)


def test_measure_recall_mrr_and_categories() -> None:
    questions = [
        evaluation.Question("q1", "doc", "a", (("r", "1.md"),)),
        evaluation.Question("q2", "doc", "b", (("r", "2.md"),)),
        evaluation.Question("q3", "code", "c", (("r", "3.py"),)),
    ]
    answers = {"a": [_r("r", "1.md")], "b": [_r("r", "x"), _r("r", "2.md")], "c": []}
    m = evaluation.measure("trial", questions, lambda q: answers[q])
    assert m.recall == pytest.approx(2 / 3) and m.mrr == pytest.approx(1.5 / 3)
    assert m.per_category == {"code": (0.0, 0.0), "doc": (1.0, 0.75)} and m.missed == ["q3"]
    text = evaluation.table([m])
    assert "| trial | 67% | 0.50 |" in text and "| doc | 100% · 0.75 |" in text
    assert evaluation.first_expected_rank([("a", "b")], [("c", "d")]) is None


def test_example_questions_are_valid() -> None:
    questions = evaluation.load(REPO_ROOT / "eval" / "example-questions.yaml")
    assert len({q.id for q in questions}) == len(questions) >= 4
    assert all(q.expected for q in questions)


# ------------------------------------------------------------------ commands


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    roots = tmp_path / "code"
    make_repo(roots, "sample", SAMPLE_FILES, "https://github.com/acme/sample.git")
    path = tmp_path / "config.toml"
    path.write_text(
        f'[auth]\ntoken_file = "{tmp_path / "api-token"}"\n'
        f'[corpus]\nroots = ["{roots}"]\n[thermal]\nenabled = false\n'
    )
    monkeypatch.setenv("CODE_ATLAS_CONFIG", str(path))
    monkeypatch.setenv("CODE_ATLAS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CODE_ATLAS_CACHE", str(tmp_path / "cache"))
    return path


def test_corpus_command_writes_manifest_and_report(
    settings_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["corpus", "--processes", "1"]) == 0
    data = settings_file.parent / "data"
    manifest = json.loads((data / "corpus.json").read_text())
    assert manifest["repos"][0]["key"] == "acme/sample"
    assert manifest["repos"][0]["host"] == "github.com"
    assert {f["path"] for f in manifest["files"]} == set(SAMPLE_FILES)
    assert "Repositories kept: **1**" in capsys.readouterr().out
    assert (data / "corpus-report.md").is_file()


def test_token_command(settings_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["token"]) == 0
    token_file = settings_file.parent / "api-token"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    out = capsys.readouterr().out
    assert "created" in out and token_file.read_text().strip() not in out
    cli.main(["token"])
    assert "already present" in capsys.readouterr().out


@pytest.mark.db
def test_index_and_search_commands(
    settings_file: Path,
    connection: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "CODE_ATLAS_DSN", connection.info.dsn + " password=" + (connection.info.password or "")
    )
    assert cli.main(["index", "--fake"]) == 1  # no manifest yet
    cli.main(["corpus", "--processes", "1", "--skip-secrets"])
    capsys.readouterr()
    assert cli.main(["index", "--fake", "--verbose"]) == 0
    assert "1 repos · 3 files read" in capsys.readouterr().out
    assert cli.main(["search", "--fake", "--excerpts", "can_receive_shared_feed", "-k", "2"]) == 0
    assert capsys.readouterr().out.startswith(" 1. acme/sample/app/sharing.py:1-3")
    assert cli.main(["search", "--fake", "--no-rerank", "--repo", "x/y", "fusion"]) == 1


def test_contract_is_up_to_date(tmp_path: Path) -> None:
    out = tmp_path / "openapi.yaml"
    assert cli.main(["openapi", "--output", str(out)]) == 0
    contract = yaml.safe_load(out.read_text())
    assert {"/v1/chat", "/v1/search", "/v1/public-config"} <= set(contract["paths"])
    assert (REPO_ROOT / "contract" / "openapi.yaml").read_text() == out.read_text(), (
        "contract/openapi.yaml is stale: run « atlas openapi --output ../contract/openapi.yaml »"
    )
