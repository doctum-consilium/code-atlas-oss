"""Shared pieces: the chunk and windows of lines."""

from __future__ import annotations

from dataclasses import dataclass

MAX_LINES = 120  # above this, a function is split into blocks
WINDOW = 60  # lines per window
OVERLAP = 12  # 20 % of the window, repeated in the next one
MAX_CHARS = 6000  # guard against endless lines (minified files)


@dataclass(frozen=True)
class Chunk:
    """A searchable passage; ``line_start`` and ``line_end`` are inclusive, from 1."""

    text: str
    line_start: int
    line_end: int
    kind: str
    symbol: str | None = None


def windows(
    lines: list[str],
    start: int,
    end: int,
    kind: str,
    symbol: str | None = None,
    size: int = WINDOW,
    overlap: int = OVERLAP,
) -> list[Chunk]:
    """Split lines ``start..end`` (1-based, inclusive) into overlapping windows.

    Windows made only of blank lines are skipped, and each window honours :data:`MAX_CHARS` by
    getting shorter if needed.
    """
    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    position = start
    while position <= end:
        bound = min(end, position + size - 1)
        bound = _bound_chars(lines, position, bound)
        text = "\n".join(lines[position - 1 : bound])
        if text.strip():
            chunks.append(Chunk(text, position, bound, kind, symbol))
        if bound >= end:
            break
        position = max(position + 1, min(position + step, bound - overlap + 1))
    return chunks


def _bound_chars(lines: list[str], start: int, end: int) -> int:
    total = 0
    for number in range(start, end + 1):
        total += len(lines[number - 1]) + 1
        if total > MAX_CHARS and number > start:
            return number - 1
    return end


def block(lines: list[str], start: int, end: int, kind: str, symbol: str | None) -> list[Chunk]:
    """One chunk if short enough, otherwise windows carrying the same symbol."""
    text = "\n".join(lines[start - 1 : end])
    if not text.strip():
        return []
    if end - start + 1 <= MAX_LINES and len(text) <= MAX_CHARS:
        return [Chunk(text, start, end, kind, symbol)]
    return windows(lines, start, end, kind, symbol)
