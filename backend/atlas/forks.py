"""GitHub fork status, read with ``gh`` and cached locally for 7 days."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

CACHE_SECONDS = 7 * 24 * 3600


class GitHubForks:
    """Asks ``gh api repos/<owner>/<name>``; only the boolean ``fork`` field is cached."""

    def __init__(self, cache: Path, refresh: bool = False) -> None:
        self.cache = cache
        self._entries: dict[str, dict[str, float | bool]] = {}
        if cache.exists() and not refresh:
            try:
                self._entries = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._entries = {}

    def __call__(self, owner: str, name: str) -> bool | None:
        """True for a fork, ``None`` when GitHub does not answer."""
        key = f"{owner}/{name}"
        entry = self._entries.get(key)
        if entry and time.time() - float(entry["read_at"]) < CACHE_SECONDS:
            return bool(entry["fork"])
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{key}", "--jq", ".fork"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = result.stdout.strip()
        if result.returncode != 0 or value not in ("true", "false"):
            return None
        fork = value == "true"
        self._entries[key] = {"fork": fork, "read_at": time.time()}
        return fork

    def save(self) -> None:
        """Write the cache (folder created if needed)."""
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps(self._entries, indent=2, sort_keys=True), encoding="utf-8")
