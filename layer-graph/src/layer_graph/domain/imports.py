"""Import statements read out of source text: TypeScript/JavaScript, the
<script> blocks of a Vue single-file component, and Python.

The TypeScript scan masks comments and string contents first, so import-like
text inside either never counts, then matches the statement shapes on the
masked text and reads each specifier back from the original.
"""

import ast
import re
from dataclasses import dataclass

# --- Constants ---------------------------------------------------------------

_IDENT = r"(?<![.\w$])"
# import x from '...', import { a, b } from '...', export * from '...',
# export { e } from '...', import type { T } from '...'.
_FROM = re.compile(
    _IDENT + r"(?:import|export)\s+(?:type\s+)?[\w*${},\s]*?\bfrom\s*(['\"])"
)
_SIDE_EFFECT = re.compile(_IDENT + r"import\s*(['\"])")
_DYNAMIC = re.compile(_IDENT + r"import\s*\(\s*(['\"])")
_REQUIRE = re.compile(_IDENT + r"require\s*\(\s*(['\"])")
_STATEMENTS = (_FROM, _SIDE_EFFECT, _DYNAMIC, _REQUIRE)
# export * from, export * as ns from, export { a } from, export type ... from.
_REEXPORT = re.compile(
    _IDENT
    + r"export\s+(?:type\s+)?(?:\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s*from\s*(['\"])"
)
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonImport:
    """One imported module: its dotted name, the names imported from it, and
    its relative level (0 for absolute)."""

    module: str
    names: tuple[str, ...]
    level: int


# --- Pure helpers: TypeScript -------------------------------------------------


def _skip_line_comment(text: str, i: int) -> int:
    end = text.find("\n", i)
    return len(text) if end < 0 else end


def _skip_block_comment(text: str, i: int) -> int:
    end = text.find("*/", i + 2)
    return len(text) if end < 0 else end + 2


def _skip_quoted(text: str, i: int, *, multiline: bool) -> int:
    """The index just past the closing quote of the literal opening at i."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        char = text[j]
        if char == "\\":
            j += 2
            continue
        if char == quote:
            return j + 1
        if char == "\n" and not multiline:
            return j
        j += 1
    return len(text)


def _masked(text: str) -> tuple[str, dict[int, int]]:
    """The text with comments blanked and string contents blanked (quotes
    kept, length kept), and each string's opening quote -> closing index."""
    out = list(text)
    strings: dict[int, int] = {}
    i = 0
    while i < len(text):
        two = text[i : i + 2]
        if two == "//":
            end = _skip_line_comment(text, i)
        elif two == "/*":
            end = _skip_block_comment(text, i)
        elif text[i] in "'\"`":
            end = _skip_quoted(text, i, multiline=text[i] == "`")
            strings[i] = end - 1
            for k in range(i + 1, end - 1):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        else:
            i += 1
            continue
        for k in range(i, end):
            if out[k] != "\n":
                out[k] = " "
        i = end
    return "".join(out), strings


def ts_specifiers(text: str) -> list[str]:
    """Every module specifier a TypeScript/JavaScript source imports
    statically, re-exports, imports dynamically or requires, in source order.
    """
    masked, strings = _masked(text)
    found: dict[int, str] = {}
    for statement in _STATEMENTS:
        for match in statement.finditer(masked):
            quote = match.start(1)
            close = strings.get(quote)
            if close is None or close <= quote:
                continue
            found.setdefault(quote, text[quote + 1 : close])
    return [found[q] for q in sorted(found)]


def reexport_specifiers(text: str) -> tuple[str, ...] | None:
    """The specifiers a barrel re-exports, in order; None when the file is not
    a barrel: it holds anything besides re-exports, or no re-export at all."""
    masked, strings = _masked(text)
    rest = list(masked)
    found: list[str] = []
    for match in _REEXPORT.finditer(masked):
        quote = match.start(1)
        close = strings.get(quote)
        if close is None or close <= quote:
            return None
        found.append(text[quote + 1 : close])
        rest[match.start() : close + 1] = " " * (close + 1 - match.start())
    if not found or "".join(rest).replace(";", " ").strip():
        return None
    return tuple(found)


def vue_scripts(text: str) -> str:
    """The <script> blocks of a Vue single-file component, joined."""
    return "\n".join(m.group(1) for m in _SCRIPT.finditer(text))


# --- Pure helpers: Python -----------------------------------------------------


def python_imports(text: str) -> list[PythonImport]:
    """Every import a Python source makes, in source order; none when the
    source does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: list[tuple[int, int, int, PythonImport]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for index, alias in enumerate(node.names):
                found.append(
                    (
                        node.lineno,
                        node.col_offset,
                        index,
                        PythonImport(alias.name, (), 0),
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            names = tuple(alias.name for alias in node.names)
            found.append(
                (
                    node.lineno,
                    node.col_offset,
                    0,
                    PythonImport(node.module or "", names, node.level),
                )
            )
    return [item for *_, item in sorted(found, key=lambda f: f[:3])]
