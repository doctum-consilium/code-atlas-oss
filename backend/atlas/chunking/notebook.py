"""Chunking a Jupyter notebook: cells only, never outputs.

The "line" numbers of a notebook chunk are **cell numbers** (from 1): an .ipynb file is JSON and
its lines mean nothing to a reader. The ``cell`` kind tells the interface.
"""

from __future__ import annotations

import json

from atlas.chunking.common import MAX_CHARS, Chunk


def chunk_notebook(text: str, max_lines: int = 60) -> list[Chunk]:
    """Group consecutive cells up to about ``max_lines`` lines of source."""
    try:
        cells = json.loads(text).get("cells", [])
    except (ValueError, AttributeError):
        return []
    chunks: list[Chunk] = []
    buffer: list[str] = []
    first = 0
    size = 0
    for number, cell in enumerate(cells, start=1):
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else str(source)
        if not source.strip():
            continue
        header = "# %% [markdown]" if cell.get("cell_type") == "markdown" else "# %%"
        piece = f"{header}\n{source.strip()}"
        n = piece.count("\n") + 1
        if buffer and (size + n > max_lines or len("\n".join(buffer)) > MAX_CHARS):
            chunks.append(Chunk("\n\n".join(buffer), first, number - 1, "cell"))
            buffer, size = [], 0
        if not buffer:
            first = number
        buffer.append(piece[:MAX_CHARS])
        size += n
    if buffer:
        chunks.append(Chunk("\n\n".join(buffer), first, len(cells), "cell"))
    return chunks
