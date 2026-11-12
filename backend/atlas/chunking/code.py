"""Structural chunking of code with tree-sitter.

Same principle for every language:

- a **function** (or method) gives one chunk, split into blocks above
  :data:`~atlas.chunking.common.MAX_LINES` lines;
- a short **container** (class, interface, impl, namespace…) gives one chunk; a long one gives a
  header chunk (up to its first member) then its members, chunked the same way;
- code between definitions (imports, constants, scripts) is grouped into windows.

A chunk's symbol is qualified by its containers: ``Class.method``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from atlas.chunking.common import MAX_LINES, Chunk, block, windows


@dataclass(frozen=True)
class Grammar:
    """tree-sitter node types that matter for one language."""

    functions: frozenset[str]
    containers: frozenset[str]
    wrappers: frozenset[str] = frozenset()  # transparent nodes (decorators, export)


def _g(functions: str, containers: str, wrappers: str = "") -> Grammar:
    return Grammar(
        frozenset(functions.split()), frozenset(containers.split()), frozenset(wrappers.split())
    )


_JS = _g(
    "function_declaration generator_function_declaration method_definition",
    "class_declaration abstract_class_declaration interface_declaration "
    "type_alias_declaration enum_declaration module internal_module",
    "export_statement",
)

GRAMMARS: dict[str, Grammar] = {
    "python": _g("function_definition", "class_definition", "decorated_definition"),
    "java": _g(
        "method_declaration constructor_declaration",
        "class_declaration interface_declaration enum_declaration record_declaration "
        "annotation_type_declaration",
    ),
    "kotlin": _g("function_declaration", "class_declaration object_declaration"),
    "dart": _g(
        "function_signature method_signature getter_signature setter_signature",
        "class_definition mixin_declaration extension_declaration enum_declaration",
    ),
    "typescript": _JS,
    "tsx": _JS,
    "javascript": _JS,
    "rust": _g(
        "function_item",
        "impl_item trait_item struct_item enum_item mod_item union_item",
    ),
    "go": _g("function_declaration method_declaration", "type_declaration"),
    "c": _g("function_definition", "struct_specifier union_specifier enum_specifier"),
    "cpp": _g(
        "function_definition",
        "class_specifier struct_specifier namespace_definition enum_specifier",
        "template_declaration",
    ),
    "csharp": _g(
        "method_declaration constructor_declaration local_function_statement",
        "class_declaration interface_declaration struct_declaration record_declaration "
        "enum_declaration namespace_declaration",
    ),
    "bash": _g("function_definition", ""),
    "php": _g(
        "function_definition method_declaration",
        "class_declaration interface_declaration trait_declaration",
    ),
}

STRUCTURED_LANGUAGES = frozenset(GRAMMARS)

_NAME_TYPES = (
    "identifier",
    "type_identifier",
    "simple_identifier",
    "property_identifier",
    "field_identifier",
    "name",
    "constant",
    "word",
)


def chunk_code(text: str, language: str) -> list[Chunk]:
    """Chunk a code file; fall back to windows if parsing fails."""
    lines = text.split("\n")
    if not text.strip():
        return []
    try:
        racine = _parse(text, language)
    except Exception:  # noqa: BLE001 -- missing grammar or unreadable file: windows
        return windows(lines, 1, len(lines), "window")
    grammar = GRAMMARS[language]
    definitions = list(_definitions(racine.children, grammar))
    chunks: list[Chunk] = []
    covered = 0  # last line already covered by a definition
    for start, end, node, kind in definitions:
        if start > covered + 1:
            chunks += windows(lines, covered + 1, start - 1, "module")
        chunks += _chunk_definition(lines, node, start, end, kind, grammar, prefix="")
        covered = max(covered, end)
    if covered < len(lines):
        chunks += windows(lines, covered + 1, len(lines), "module")
    return chunks


def _parse(text: str, language: str) -> Any:
    from tree_sitter_language_pack import get_parser

    return get_parser(cast(Any, language)).parse(text.encode("utf-8")).root_node


def _definitions(children: list[Any], grammar: Grammar) -> Iterator[tuple[int, int, Any, str]]:
    """Direct definitions among ``children``: ``(start line, end line, node, kind)``.

    A Dart signature is followed by its body (``function_body``): the definition extends to the
    end of that body.
    """
    for i, node in enumerate(children):
        inner = _unwrap(node, grammar)
        if inner is None:
            continue
        is_function = inner.type in grammar.functions or inner.type == "variable_declarator"
        kind = "function" if is_function else "class"
        end_node = node
        if i + 1 < len(children) and children[i + 1].type == "function_body":
            end_node = children[i + 1]
        yield node.start_point[0] + 1, end_node.end_point[0] + 1, inner, kind


def _unwrap(node: Any, grammar: Grammar) -> Any | None:
    """The definition node, going through wrappers (decorator, ``export``)."""
    if node.type in grammar.functions or node.type in grammar.containers:
        return node
    if node.type in grammar.wrappers:
        for child in node.named_children:
            found = _unwrap(child, grammar)
            if found is not None:
                return found
    if node.type == "lexical_declaration":  # export const f = () => …
        for declarator in node.named_children:
            value = declarator.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function_expression"):
                return declarator
    if node.type == "method_signature":  # Dart: wraps function_signature
        return node
    return None


def _chunk_definition(
    lines: list[str],
    node: Any,
    start: int,
    end: int,
    kind: str,
    grammar: Grammar,
    prefix: str,
) -> list[Chunk]:
    name = name_of(node)
    symbol = f"{prefix}{name}" if name else (prefix.rstrip(".") or None)
    if kind == "function" or end - start + 1 <= MAX_LINES:
        return block(lines, start, end, "method" if prefix else kind, symbol)
    body_node = _body(node)
    members = list(_definitions(body_node.children, grammar)) if body_node is not None else []
    if not members:
        return block(lines, start, end, kind, symbol)
    chunks: list[Chunk] = []
    first = members[0][0]
    chunks += block(lines, start, max(start, first - 1), "header", symbol)
    covered = first - 1
    sub_prefix = f"{symbol}." if symbol else ""
    for m_start, m_end, m_node, m_kind in members:
        if m_start > covered + 1:
            chunks += windows(lines, covered + 1, m_start - 1, "members", symbol)
        chunks += _chunk_definition(lines, m_node, m_start, m_end, m_kind, grammar, sub_prefix)
        covered = max(covered, m_end)
    if covered < end:
        chunks += windows(lines, covered + 1, end, "members", symbol)
    return chunks


def _body(node: Any) -> Any | None:
    """The node holding a container's members (class body, impl block…)."""
    body_node = node.child_by_field_name("body")
    if body_node is not None:
        return body_node
    for child in node.named_children:
        if child.type.endswith(("body", "_list", "declaration_list")):
            return child
    return None


def name_of(node: Any) -> str | None:
    """Name of a definition: ``name`` field (or ``type`` for an ``impl``), else the first
    identifier found at shallow depth."""
    for field_name in ("name", "type", "declarator"):
        target = node.child_by_field_name(field_name)
        if target is not None:
            name = _first_identifier(target, depth=3)
            if name:
                return name
    return _first_identifier(node, depth=2, root=True)


def _first_identifier(node: Any, depth: int, root: bool = False) -> str | None:
    if not root and node.type in _NAME_TYPES:
        return str(node.text.decode("utf-8", "replace"))
    if depth == 0:
        return None
    for child in node.named_children:
        if child.type in ("parameters", "formal_parameters", "parameter_list", "block", "body"):
            continue
        found = _first_identifier(child, depth - 1)
        if found:
            return found
    return None
