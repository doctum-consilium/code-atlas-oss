"""Remote-model policy: which gateway models may receive code extracts, and why.

Three gates, in order:

1. the alias is listed in the policy file (closed list);
2. its provider retains nothing *today*: for ``aws-bedrock`` the account's data-retention mode is
   read (``none`` required); for ``date`` the documented check is younger than N days (warning);
3. the gateway really serves the alias (``/v1/models``).

This module only decides; it sends nothing.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AWS_CACHE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class Provider:
    """A provider and how its zero retention is checked."""

    name: str
    check: str  # "date" or "aws-bedrock"
    verified_on: dt.date
    source: str
    summary: str
    region: str | None = None
    reread_after_days: int = 90


@dataclass(frozen=True)
class Verdict:
    """Decision for one remote alias."""

    alias: str
    provider: str
    allowed: bool
    reason: str
    verified_on: str
    source: str
    warning: str | None = None


@dataclass(frozen=True)
class Policy:
    """Content of the policy file."""

    providers: dict[str, Provider]
    models: dict[str, str]  # alias -> provider

    @classmethod
    def empty(cls) -> Policy:
        """No remote model allowed."""
        return cls({}, {})

    @classmethod
    def load(cls, path: Path) -> Policy:
        """Read the policy file; a missing file means no remote model."""
        if not path.is_file():
            return cls.empty()
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        providers = {
            name: Provider(
                name=name,
                check=p["check"],
                verified_on=dt.date.fromisoformat(str(p["verified_on"])),
                source=p.get("source", ""),
                summary=p.get("summary", ""),
                region=p.get("region"),
                reread_after_days=int(p.get("reread_after_days", 90)),
            )
            for name, p in raw.get("providers", {}).items()
        }
        models = {m["alias"]: m["provider"] for m in raw.get("models", [])}
        unknown = set(models.values()) - set(providers)
        if unknown:
            raise ValueError(f"Provider without a policy: {sorted(unknown)}")
        return cls(providers, models)


AwsReader = Callable[[str], str | None]


def read_bedrock_mode(region: str) -> str | None:
    """The account's Bedrock data-retention mode (``none``, ``default``…), or ``None``."""
    try:
        result = subprocess.run(
            [
                "aws",
                "bedrock",
                "get-account-data-retention",
                "--region",
                region,
                "--query",
                "mode",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    mode = result.stdout.strip()
    return mode if result.returncode == 0 and mode else None


class Gatekeeper:
    """Applies the policy; keeps the AWS reading in memory for 24 h."""

    def __init__(
        self,
        policy: Policy,
        aws_reader: AwsReader = read_bedrock_mode,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.policy = policy
        self._aws_reader = aws_reader
        self._today = today
        self._aws_cache: dict[str, tuple[float, str | None]] = {}

    def aws_mode(self, region: str) -> str | None:
        """Bedrock mode of the region, read at most once a day."""
        cached = self._aws_cache.get(region)
        if cached and time.monotonic() - cached[0] < AWS_CACHE_SECONDS:
            return cached[1]
        mode = self._aws_reader(region)
        self._aws_cache[region] = (time.monotonic(), mode)
        return mode

    def forget(self) -> None:
        """Force a new AWS reading on the next call."""
        self._aws_cache.clear()

    def judge(self, alias: str, served: set[str] | None = None) -> Verdict:
        """Verdict for one alias; ``served`` = aliases the gateway declares (None = unknown)."""
        name = self.policy.models.get(alias)
        if name is None:
            return Verdict(alias, "?", False, "alias not in the policy file", "", "")
        p = self.policy.providers[name]
        base: dict[str, Any] = {
            "alias": alias,
            "provider": name,
            "verified_on": p.verified_on.isoformat(),
            "source": p.source,
        }
        warning = None
        if p.check == "aws-bedrock":
            mode = self.aws_mode(p.region or "us-east-1")
            if mode != "none":
                return Verdict(
                    **base,
                    allowed=False,
                    reason=f"Bedrock retention mode is '{mode or 'unreadable'}', not 'none'",
                )
            base["verified_on"] = self._today().isoformat()
        elif p.check == "date":
            age = (self._today() - p.verified_on).days
            if age > p.reread_after_days:
                warning = f"policy checked {age} days ago: read it again ({p.source})"
        else:
            return Verdict(**base, allowed=False, reason=f"unknown check '{p.check}'")
        if served is not None and alias not in served:
            return Verdict(**base, allowed=False, reason="the gateway does not serve this alias")
        return Verdict(**base, allowed=True, reason=p.summary, warning=warning)

    def all(self, served: set[str] | None = None) -> list[Verdict]:
        """Verdict for every listed alias."""
        return [self.judge(alias, served) for alias in self.policy.models]
