"""Secret detection before indexing, with detect-secrets.

A line where a secret is detected is replaced by a mask before chunking; a file that holds a
private key (or cannot be scanned) is excluded entirely, because the key spans several lines. The
report only holds the path, the detector and the line number: **never the value**, nor any
excerpt of the line.

The entropy detectors (random base64 / hex strings) and the public-IP detector are disabled: on
source code they mostly flag hashes and identifiers and would drop useful files.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

DETECTORS = (
    "ArtifactoryDetector",
    "AWSKeyDetector",
    "AzureStorageKeyDetector",
    "BasicAuthDetector",
    "CloudantDetector",
    "DiscordBotTokenDetector",
    "GitHubTokenDetector",
    "GitLabTokenDetector",
    "IbmCloudIamDetector",
    "IbmCosHmacDetector",
    "JwtTokenDetector",
    "KeywordDetector",
    "MailchimpDetector",
    "NpmDetector",
    "OpenAIDetector",
    "PrivateKeyDetector",
    "PypiTokenDetector",
    "SendGridDetector",
    "SlackDetector",
    "SoftlayerDetector",
    "SquareOAuthDetector",
    "StripeDetector",
    "TelegramBotTokenDetector",
    "TwilioKeyDetector",
)

# Detectors whose alert excludes the whole file rather than one line.
EXCLUDE_WHOLE_FILE = frozenset({"Private Key", "read error"})

MASK = "[line masked by code-atlas: probable secret]"


@dataclass(frozen=True)
class Alert:
    """A probable secret: where it is and which detector saw it, never its value."""

    path: str
    detector: str
    line: int


def scan(path: Path) -> list[tuple[str, int]]:
    """``(detector, line)`` for each probable secret in the file."""
    from detect_secrets.core.scan import scan_file
    from detect_secrets.settings import transient_settings

    settings = {"plugins_used": [{"name": name} for name in DETECTORS]}
    with transient_settings(settings):
        return sorted({(s.type, s.line_number) for s in scan_file(str(path))})


def _scan_one(argument: tuple[str, Path]) -> list[Alert]:
    key, path = argument
    try:
        found = scan(path)
    except Exception:  # noqa: BLE001 -- an unreadable file is excluded, not fatal
        return [Alert(key, "read error", 0)]
    return [Alert(key, detector, line) for detector, line in found]


def scan_all(files: Iterable[tuple[str, Path]], processes: int = 8) -> list[Alert]:
    """Parallel scan; ``files`` yields ``(display key, absolute path)``."""
    items = list(files)
    if not items:
        return []
    with ProcessPoolExecutor(max_workers=processes) as pool:
        return [alert for batch in pool.map(_scan_one, items, chunksize=64) for alert in batch]


def split(alerts: Iterable[Alert]) -> tuple[set[str], dict[str, list[int]]]:
    """Files to exclude, and lines to mask (``{file: [lines]}``)."""
    alerts = list(alerts)
    excluded = {a.path for a in alerts if a.detector in EXCLUDE_WHOLE_FILE}
    masked: dict[str, set[int]] = {}
    for a in alerts:
        if a.path not in excluded:
            masked.setdefault(a.path, set()).add(a.line)
    return excluded, {path: sorted(lines) for path, lines in masked.items()}


def mask(text: str, lines: Iterable[int]) -> str:
    """Replace the given lines (numbered from 1) with :data:`MASK`."""
    targets = set(lines)
    if not targets:
        return text
    parts = text.splitlines(keepends=True)
    for number in targets:
        if 1 <= number <= len(parts):
            end = "\n" if parts[number - 1].endswith("\n") else ""
            parts[number - 1] = MASK + end
    return "".join(parts)
