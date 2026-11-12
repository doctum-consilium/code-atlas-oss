"""Splitting a file into searchable chunks.

Code is split along its structure (one function, method or short class per chunk) with
tree-sitter; documentation is split by heading; anything else by windows of lines. Line numbers
stay those of the file: a citation points at real lines.
"""

from __future__ import annotations

from atlas.chunking.common import Chunk
from atlas.chunking.text import chunk_text

__all__ = ["Chunk", "chunk"]


def chunk(text: str, language: str, path: str) -> list[Chunk]:
    """Split ``text`` according to its language; never returns an empty chunk."""
    from atlas.chunking.code import STRUCTURED_LANGUAGES, chunk_code
    from atlas.chunking.notebook import chunk_notebook

    if language == "notebook":
        return chunk_notebook(text)
    if language in STRUCTURED_LANGUAGES:
        return chunk_code(text, language)
    return chunk_text(text, language, path)
