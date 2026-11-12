"""Chunking documentation (by heading) and other formats (by windows of lines)."""

from __future__ import annotations

import re

from atlas.chunking.common import Chunk, block, windows

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_FENCE = re.compile(r"^\s*(```|~~~)")
_TEX_HEADING = re.compile(r"^\s*\\(part|chapter|section|subsection|subsubsection)\*?\{(.+?)\}")
_TEX_LEVELS = {"part": 1, "chapter": 2, "section": 3, "subsection": 4, "subsubsection": 5}


def chunk_text(text: str, language: str, path: str) -> list[Chunk]:
    """Markdown and LaTeX by section (heading trail as symbol); anything else by windows."""
    lines = text.split("\n")
    if not text.strip():
        return []
    if language == "markdown":
        return _by_sections(lines, _markdown_headings(lines))
    if language == "latex":
        return _by_sections(lines, _latex_headings(lines))
    return windows(lines, 1, len(lines), "window")


def _markdown_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    in_code = False
    for number, line in enumerate(lines, start=1):
        if _MD_FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = _MD_HEADING.match(line)
        if match:
            headings.append((number, len(match[1]), match[2]))
    return headings


def _latex_headings(lines: list[str]) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    for number, line in enumerate(lines, start=1):
        match = _TEX_HEADING.match(line)
        if match:
            headings.append((number, _TEX_LEVELS[match[1]], match[2]))
    return headings


def _by_sections(lines: list[str], headings: list[tuple[int, int, str]]) -> list[Chunk]:
    """A section runs from its heading to the next one; its symbol is the trail "A > B"."""
    if not headings:
        return windows(lines, 1, len(lines), "window")
    chunks: list[Chunk] = []
    if headings[0][0] > 1:
        chunks += block(lines, 1, headings[0][0] - 1, "section", None)
    trail: list[tuple[int, str]] = []
    for i, (start, level, title) in enumerate(headings):
        while trail and trail[-1][0] >= level:
            trail.pop()
        trail.append((level, title))
        end = headings[i + 1][0] - 1 if i + 1 < len(headings) else len(lines)
        chunks += block(lines, start, end, "section", " > ".join(t for _l, t in trail))
    return chunks
