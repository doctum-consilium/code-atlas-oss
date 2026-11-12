"""Lexical text: what the word search (BM25) indexes and queries.

Code names things in ``camelCase`` or ``snake_case``; a question says "can receive the share".
To make them meet, every identifier is indexed three times: as is (lower case), split into words,
and glued back without separators. Accented words also get an unaccented form.

The same transformation applies to indexing and to the question: it, not the pg_search analyzer,
is the source of truth.
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN = re.compile(r"\w+", re.UNICODE)
_PARTS = re.compile(r"[A-ZÀ-Þ]+(?=[A-ZÀ-Þ][a-zß-ÿ])|[A-ZÀ-Þ]?[a-zß-ÿ]+|[A-ZÀ-Þ]+|\d+")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")

# Words too frequent to help ranking (English and French); removed from the question only.
STOP_WORDS = frozenset(
    """
    the a an of to in on for and or is are was be with by from at as it this that how what where
    which do does did i my me we you your can should would
    le la les un une des du de d l et ou en au aux à est sont dans pour par sur avec sans que qui
    quoi quel quelle quels quelles comment où ce cet cette ces se sa son ses mon ma mes je j il
    on nous vous ils elle elles y ne pas plus moins fait faire ai as avons
    """.split()  # noqa: SIM905 -- long list, more readable as text
)


def strip_accents(word: str) -> str:
    """ "réglage" -> "reglage"."""
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def variants(token: str) -> list[str]:
    """Indexed forms of a token: itself, its parts, the glued form, without accents."""
    forms = [token.lower()]
    parts = [p.lower() for piece in token.split("_") for p in _PARTS.findall(piece)]
    if len(parts) > 1:
        forms += parts
        forms.append("".join(parts))
    result: list[str] = []
    for form in forms:
        for f in (form, strip_accents(form)):
            if f and f not in result:
                result.append(f)
    return result


def lexical_text(*texts: str | None) -> str:
    """Text to index: the variants of every token, separated by spaces."""
    output: list[str] = []
    for text in texts:
        if not text:
            continue
        for token in _TOKEN.findall(text):
            output += variants(token)
    return " ".join(output)


def lexical_query(question: str) -> str:
    """De-duplicated search terms without stop words; empty if nothing useful."""
    terms: list[str] = []
    for token in _TOKEN.findall(question):
        for form in variants(token):
            if form not in STOP_WORDS and form not in terms:
                terms.append(form)
    return " ".join(terms)


def identifiers(question: str) -> list[str]:
    """Question tokens that look like code names (``_x_y``, ``fooBar``, ``Foo.bar``).

    They get a bonus when they exactly match a chunk's symbol.
    """
    found: list[str] = []
    for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", question):
        for token in raw.split("."):
            code_like = "_" in token.strip("_") or (
                any(c.isupper() for c in token[1:]) and any(c.islower() for c in token)
            )
            new = token not in found
            if _IDENTIFIER.match(token) and (code_like or token.startswith("_")) and new:
                found.append(token)
    return found
