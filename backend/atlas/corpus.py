"""Corpus selection: which repositories and files code-atlas may index.

The module only reads files tracked by git and never writes into the repositories. It decides in
three steps:

1. repositories: accepted owner (if a list is set), not a fork (if asked), not excluded by name,
   not a second clone of the same remote, at least one tracked file;
2. files: useful file type, bounded size, neither binary, generated nor a key file;
3. duplicates: identical content (same git blob) is kept once, in the preferred owner's repo.

Secret detection lives in :mod:`atlas.secrets`; this module has no third-party dependency.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from atlas.config import CorpusSettings

# A fork whose status is unknown (GitHub unreachable) is treated as a fork: what cannot be
# classified is not indexed. ``None`` = unknown.
ForkSource = Callable[[str, str], bool | None]

_REMOTE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?|ssh://(?:[^@/]+@)?|[^@/]+@)"
    r"(?P<host>[A-Za-z0-9_.-]+)(?::\d+)?[:/]"
    r"(?P<owner>[A-Za-z0-9_.~/-]+?)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".dart": "dart",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".ipynb": "notebook",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".php": "php",
    ".swift": "swift",
    ".lua": "lua",
    ".r": "r",
    ".cl": "opencl",
    ".tf": "terraform",
    ".rb": "ruby",
    ".scala": "scala",
}

EXACT_NAMES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
    "package.json": "json",
    "pubspec.yaml": "yaml",
    ".env.example": "dotenv",
    ".env.sample": "dotenv",
    ".env.template": "dotenv",
}

DOC_LANGUAGES = {"markdown", "rst", "latex"}
CONFIG_LANGUAGES = {"yaml", "toml", "json", "dockerfile", "make", "cmake", "terraform", "dotenv"}

IGNORED_DIRS = {
    "node_modules",
    "vendor",
    "third_party",
    "build",
    "dist",
    "out",
    "target",
    ".dart_tool",
    "__pycache__",
    ".venv",
    "venv",
    "Pods",
    ".gradle",
    ".idea",
    "coverage",
    "site-packages",
}

GENERATED_PATTERNS = (
    "*.lock",
    "*-lock.json",
    "*-lock.yaml",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.g.dart",
    "*.freezed.dart",
    "*.pb.go",
    "*_pb2.py",
    "*.generated.*",
)

# Files that hold secrets by nature: excluded before being read.
KEY_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_ed25519*",
    "*.kdbx",
    "credentials*",
    "*secret*.y*ml",
)
# A configuration template without real values stays useful to search.
TOLERATED_KEY_PATTERNS = (".env.example", ".env.sample", ".env.template")

MODE_SYMLINK = "120000"
MODE_SUBMODULE = "160000"


@dataclass(frozen=True)
class Repo:
    """A git working tree found under a root."""

    path: Path
    host: str | None
    owner: str | None
    name: str | None
    remote: str | None

    @property
    def key(self) -> str:
        """``owner/name`` from the remote, or ``local/<folder>`` without a remote."""
        if self.owner and self.name:
            return f"{self.owner}/{self.name}"
        return f"local/{self.path.name}"


@dataclass(frozen=True)
class Decision:
    """Verdict on a repository: kept or not, and why."""

    repo: Repo
    kept: bool
    reason: str


@dataclass(frozen=True)
class GitEntry:
    """One line of ``git ls-files -s``."""

    mode: str
    blob: str
    path: str


@dataclass(frozen=True)
class File:
    """A file selected for indexing."""

    repo: str
    path: str
    blob: str
    size: int
    language: str
    type: str


@dataclass
class Report:
    """Full selection result, serialisable for the indexer."""

    decisions: list[Decision]
    commits: dict[str, str]
    files: list[File]
    skipped: Counter[str]
    duplicates: list[tuple[str, str, str]]  # (blob, kept, skipped)

    def kept(self) -> list[Decision]:
        """Positive decisions, in discovery order."""
        return [d for d in self.decisions if d.kept]


def parse_remote(url: str | None) -> tuple[str, str, str] | None:
    """``(host, owner, name)`` from an HTTPS or SSH git URL (any host), else ``None``."""
    if not url:
        return None
    match = _REMOTE.match(url.strip())
    if not match:
        return None
    return match["host"].lower(), match["owner"], match["name"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",  # a non UTF-8 file name must not stop everything
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def discover(roots: Iterable[Path]) -> list[Repo]:
    """Direct subfolders that are git repositories, sorted by path."""
    repos: list[Repo] = []
    for root in roots:
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            if not (folder / ".git").exists():
                continue
            remote = _git(folder, "remote", "get-url", "origin").strip() or None
            parsed = parse_remote(remote)
            host, owner, name = parsed if parsed else (None, None, None)
            repos.append(Repo(folder, host, owner, name, remote))
    return repos


def list_tracked(repo: Path) -> list[GitEntry]:
    """Files tracked by git, without submodules, symlinks or non UTF-8 names."""
    raw = _git(repo, "ls-files", "-s", "-z")
    entries: list[GitEntry] = []
    for line in filter(None, raw.split("\0")):
        header, _, path = line.partition("\t")
        mode, blob, _stage = header.split(" ")
        if mode in (MODE_SYMLINK, MODE_SUBMODULE) or not _is_utf8(path):
            continue
        entries.append(GitEntry(mode=mode, blob=blob, path=path))
    return entries


def decide_repos(
    repos: list[Repo],
    settings: CorpusSettings,
    is_fork: ForkSource,
    tracked_count: Callable[[Repo], int],
) -> list[Decision]:
    """Apply the repository rules in a fixed order; the first refusal wins."""
    decisions: list[Decision] = []
    seen_remotes: dict[tuple[str, str, str], Repo] = {}
    # A second clone of the same remote: keep the one whose folder is named like the repo.
    order = sorted(repos, key=lambda r: (r.path.name != r.name, str(r.path)))
    for repo in order:
        decisions.append(_decide(repo, settings, is_fork, tracked_count, seen_remotes))
    rank = {r.path: i for i, r in enumerate(repos)}
    return sorted(decisions, key=lambda d: rank[d.repo.path])


def _decide(
    repo: Repo,
    settings: CorpusSettings,
    is_fork: ForkSource,
    tracked_count: Callable[[Repo], int],
    seen_remotes: dict[tuple[str, str, str], Repo],
) -> Decision:
    if settings.owners and repo.owner not in settings.owners:
        return Decision(repo, False, f"owner not listed ({repo.owner or 'no remote'})")
    if repo.key in settings.exclude:
        return Decision(repo, False, f"excluded: {settings.exclude[repo.key]}")
    remote_key = None
    if repo.host and repo.owner and repo.name:
        remote_key = (repo.host, repo.owner.lower(), repo.name.lower())
        if remote_key in seen_remotes:
            return Decision(repo, False, f"second clone of {seen_remotes[remote_key].path.name}")
    if settings.exclude_forks and repo.host == "github.com" and repo.owner and repo.name:
        fork = is_fork(repo.owner, repo.name)
        if fork is None:
            return Decision(repo, False, "fork status unknown (GitHub unreachable)")
        if fork:
            return Decision(repo, False, "fork of another repository")
    if tracked_count(repo) == 0:
        return Decision(repo, False, "no tracked file")
    if remote_key:
        seen_remotes[remote_key] = repo
    return Decision(repo, True, "kept")


def classify(path: str) -> tuple[str, str] | None:
    """``(language, type)`` of a path, or ``None`` if the file type is not indexed."""
    pure = PurePosixPath(path)
    language = EXACT_NAMES.get(pure.name) or LANGUAGES.get(pure.suffix.lower())
    if language is None:
        return None
    if language in DOC_LANGUAGES:
        return language, "doc"
    if language in CONFIG_LANGUAGES:
        return language, "config"
    if _is_test(pure):
        return language, "test"
    return language, "code"


def _is_test(path: PurePosixPath) -> bool:
    if any(part in ("test", "tests", "__tests__", "spec") for part in path.parts[:-1]):
        return True
    name = path.name
    return (
        name.startswith("test_")
        or path.stem.endswith(("_test", "Test", "Tests"))
        or ".spec." in name
        or ".test." in name
    )


def skip_reason(path: str, size: int, head: bytes, max_bytes: int) -> str | None:
    """Why a file is skipped, or ``None`` if it is kept.

    Args:
        path: POSIX path relative to the repository.
        size: Size on disk, in bytes.
        head: First bytes of the file (8 KiB is enough) to detect binaries.
        max_bytes: Above this size a file is treated as generated or data.
    """
    pure = PurePosixPath(path)
    if any(part in IGNORED_DIRS for part in pure.parts[:-1]):
        return "ignored folder"
    name = pure.name
    if not any(fnmatch.fnmatch(name, p) for p in TOLERATED_KEY_PATTERNS) and any(
        fnmatch.fnmatch(name, p) for p in KEY_PATTERNS
    ):
        return "key or environment file"
    if any(fnmatch.fnmatch(name, p) for p in GENERATED_PATTERNS):
        return "generated file"
    if classify(path) is None:
        return "file type not indexed"
    if size > max_bytes:
        return "too large"
    if b"\0" in head:
        return "binary"
    return None


def select_files(
    decisions: list[Decision],
    settings: CorpusSettings,
    lister: Callable[[Path], list[GitEntry]] = list_tracked,
) -> tuple[list[File], Counter[str], list[tuple[str, str, str]]]:
    """Useful files of the kept repositories, de-duplicated by blob."""
    owner_rank = {o: i for i, o in enumerate(settings.owners)}
    kept = sorted(
        (d.repo for d in decisions if d.kept),
        key=lambda r: (owner_rank.get(r.owner or "", 99), str(r.path)),
    )
    skipped: Counter[str] = Counter()
    by_blob: dict[str, File] = {}
    duplicates: list[tuple[str, str, str]] = []
    selected: list[File] = []
    for repo in kept:
        for entry in lister(repo.path):
            absolute = repo.path / entry.path
            try:
                size = absolute.stat().st_size
                with absolute.open("rb") as stream:
                    head = stream.read(8192)
            except OSError:
                skipped["unreadable or missing on disk"] += 1
                continue
            reason = skip_reason(entry.path, size, head, settings.max_file_bytes)
            if reason:
                skipped[reason] += 1
                continue
            language, type_ = classify(entry.path) or ("", "")
            file = File(repo.key, entry.path, entry.blob, size, language, type_)
            if entry.blob in by_blob:
                first = by_blob[entry.blob]
                duplicates.append(
                    (entry.blob, f"{first.repo}/{first.path}", f"{file.repo}/{file.path}")
                )
                skipped["duplicate of a kept file"] += 1
                continue
            by_blob[entry.blob] = file
            selected.append(file)
    return selected, skipped, duplicates


def build(settings: CorpusSettings, is_fork: ForkSource) -> Report:
    """Discovery, decisions and selection; reads only the local disk and ``is_fork``."""
    repos = discover(settings.roots)
    decisions = decide_repos(
        repos, settings, is_fork, tracked_count=lambda r: len(list_tracked(r.path))
    )
    commits = {
        d.repo.key: _git(d.repo.path, "rev-parse", "HEAD").strip() for d in decisions if d.kept
    }
    files, skipped, duplicates = select_files(decisions, settings)
    return Report(decisions, commits, files, skipped, duplicates)
