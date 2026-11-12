"""Chunking: exact function and class bounds, sections, windows, notebooks."""

from __future__ import annotations

import itertools
import json

import pytest

from atlas.chunking import chunk
from atlas.chunking.common import MAX_CHARS, MAX_LINES, windows


def _summary(text: str, language: str) -> list[tuple[str, str | None, int, int]]:
    return [(m.kind, m.symbol, m.line_start, m.line_end) for m in chunk(text, language, "x")]


def test_python_functions_classes_and_decorators() -> None:
    source = (
        "import os\n"  # 1
        "\n"  # 2
        "@cache\n"  # 3
        "def f(a):\n"  # 4
        "    return a\n"  # 5
        "\n"  # 6
        "class A:\n"  # 7
        "    def m(self):\n"  # 8
        "        return 1\n"  # 9
    )
    # Blank line 6, between two definitions, gives no chunk.
    assert _summary(source, "python") == [
        ("module", None, 1, 2),
        ("function", "f", 3, 5),
        ("class", "A", 7, 9),
    ]


def test_long_class_gives_header_then_qualified_methods() -> None:
    corps = "".join(f"    def m{i}(self):\n" + "        x = 1\n" * 50 for i in range(3))
    source = "class Big:\n    '''doc'''\n" + corps
    summary = _summary(source, "python")
    assert summary[0] == ("header", "Big", 1, 2)
    assert [s for _g, s, _d, _f in summary[1:]] == ["Big.m0", "Big.m1", "Big.m2"]
    assert all(g == "method" for g, *_ in summary[1:])
    assert summary[1][2:] == (3, 53)


def test_too_long_function_is_split_with_overlap() -> None:
    source = "def long():\n" + "    x = 1\n" * (MAX_LINES + 80)
    chunks = chunk(source, "python", "x")
    assert len(chunks) > 1
    assert {m.symbol for m in chunks} == {"long"}
    for before, after in itertools.pairwise(chunks):
        assert after.line_start <= before.line_end  # windows overlap


def test_dart_signature_and_body_stay_together() -> None:
    source = (
        "import 'x.dart';\n"
        "class A {\n"
        "  int f(int y) {\n"
        "    return y;\n"
        "  }\n"
        "}\n"
        "void main() {\n"
        "  print(1);\n"
        "}\n"
    )
    summary = _summary(source, "dart")
    assert ("class", "A", 2, 6) in summary
    assert ("function", "main", 7, 9) in summary


def test_typescript_export_and_arrow_function() -> None:
    source = "export function f(a: number) { return a }\nexport const g = (x: number) => x\n"
    assert _summary(source, "typescript") == [("function", "f", 1, 1), ("function", "g", 2, 2)]


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("java", "class A {\n  int f() { return 1; }\n}\n", ("class", "A", 1, 3)),
        ("go", "package p\nfunc F() {}\n", ("function", "F", 2, 2)),
        ("rust", "fn f() {}\n", ("function", "f", 1, 1)),
        ("kotlin", "fun top() = 2\n", ("function", "top", 1, 1)),
        ("bash", "f() { echo 1; }\n", ("function", "f", 1, 1)),
        ("csharp", "class A { int F(){return 1;} }\n", ("class", "A", 1, 1)),
    ],
)
def test_autres_languages(language: str, source: str, expected: tuple[str, str, int, int]) -> None:
    assert expected in _summary(source, language)


def test_markdown_by_headings_ignoring_headings_in_code() -> None:
    source = "intro\n# Title\ntext\n```\n# not a title\n```\n## Sub\nmore\n# Other\nend\n"
    assert _summary(source, "markdown") == [
        ("section", None, 1, 1),
        ("section", "Title", 2, 6),
        ("section", "Title > Sub", 7, 8),
        ("section", "Other", 9, 11),
    ]


def test_latex_by_sections() -> None:
    source = "\\section{One}\na\n\\subsection{Two}\nb\n\\section{Three}\nc\n"
    assert [s for _g, s, _d, _f in _summary(source, "latex")] == ["One", "One > Two", "Three"]


def test_notebook_cells_grouped_without_outputs() -> None:
    cells = [
        {"cell_type": "markdown", "source": ["# Title\n", "text"]},
        {"cell_type": "code", "source": "x = 1", "outputs": [{"text": "OUTPUT"}]},
        {"cell_type": "code", "source": ""},
    ]
    chunks = chunk(json.dumps({"cells": cells}), "notebook", "n.ipynb")
    assert len(chunks) == 1
    assert chunks[0].kind == "cell"
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 3)
    assert "OUTPUT" not in chunks[0].text and "x = 1" in chunks[0].text


def test_unreadable_notebook() -> None:
    assert chunk("not json", "notebook", "n.ipynb") == []


def test_windows_bounded_in_chars_without_empty_chunk() -> None:
    lines = ["x" * 3000] * 5 + [""] * 70
    chunks = windows(lines, 1, len(lines), "window")
    assert all(len(m.text) <= MAX_CHARS for m in chunks)
    assert all(m.text.strip() for m in chunks)
    assert chunks[0].line_start == 1


def test_empty_file_and_unstructured_formats() -> None:
    assert chunk("   \n", "python", "x") == []
    assert _summary("a: 1\nb: 2\n", "yaml") == [("window", None, 1, 3)]


def test_code_illisible_retombe_sur_des_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas.chunking import code

    def broken(*_a: object) -> None:
        raise RuntimeError("missing grammar")

    monkeypatch.setattr(code, "_parse", broken)
    assert [m.kind for m in chunk("x = 1\n", "python", "x")] == ["window"]
