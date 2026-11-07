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
# The clause between the last import/export keyword and `from`.
_KEYWORD = re.compile(r"(?<![.\w$])(import|export)\b")
_CLAUSE = re.compile(
    r"^(?:type\s+)?(?:(?P<default>[\w$]+)\s*(?:,\s*)?)?"
    r"(?:\{(?P<names>[^}]*)\}|(?P<star>\*(?:\s+as\s+[\w$]+)?))?\s*$"
)
_LOCAL_DECLARATION = re.compile(
    r"(?<![.\w$])export\s+(?:declare\s+)?"
    r"(?:(?:async\s+)?function\s*\*?|(?:abstract\s+)?class|const\s+enum|const|let|var"
    r"|interface|type|enum|namespace|module)\s+([\w$]+)"
)
_LOCAL_DEFAULT = re.compile(r"(?<![.\w$])export\s+default\b")
_LOCAL_LIST = re.compile(r"(?<![.\w$])export\s+(?:type\s+)?\{([^}]*)\}(?!\s*from\b)")
_NAMED_REEXPORT = re.compile(
    r"(?<![.\w$])export\s+(?:type\s+)?\{([^}]*)\}\s*from\s*(['\"])"
)
_NAMESPACE_REEXPORT = re.compile(
    r"(?<![.\w$])export\s+(?:type\s+)?\*\s+as\s+([\w$]+)\s*from\s*(['\"])"
)
_STAR_REEXPORT = re.compile(r"(?<![.\w$])export\s+(?:type\s+)?\*\s*from\s*(['\"])")
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonImport:
    """One imported module: its dotted name, the names imported from it, and
    its relative level (0 for absolute)."""

    module: str
    names: tuple[str, ...]
    level: int


@dataclass(frozen=True, slots=True)
class TsImport:
    """One TypeScript/JavaScript import statement: its specifier, and the
    source-side names it binds (`default` for a default import), or None
    when it binds the whole module (namespace, side effect, require,
    dynamic import, export *)."""

    specifier: str
    names: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ExportSurface:
    """What a module exports: names it declares, named re-exports as
    (exported, imported, specifier) with imported `*` for `export * as`, and
    the specifiers of its `export *`."""

    local: frozenset[str]
    named: tuple[tuple[str, str, str], ...]
    stars: tuple[str, ...]


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


def _items(listing: str) -> list[tuple[str, str]]:
    """`a, type b, c as d` as (source name, bound name) pairs."""
    pairs: list[tuple[str, str]] = []
    for item in listing.split(","):
        words = item.split()
        if words and words[0] == "type" and len(words) > 1:
            words = words[1:]
        if not words:
            continue
        if len(words) == 3 and words[1] == "as":
            pairs.append((words[0], words[2]))
        else:
            pairs.append((words[0], words[0]))
    return pairs


def _bound_names(span: str) -> tuple[str, ...] | None:
    """The names an import/export ... from span binds, or None for a whole
    module or a clause not understood."""
    keywords = list(_KEYWORD.finditer(span))
    if not keywords:
        return None
    last = keywords[-1]
    clause = span[last.end() :].strip()
    clause = clause[: -len("from")].strip() if clause.endswith("from") else clause
    match = _CLAUSE.match(clause)
    if match is None or match.group("star"):
        return None
    default = match.group("default")
    if last.group(1) == "export" and default:
        return None
    names = ["default"] if default else []
    names += [source for source, _ in _items(match.group("names") or "")]
    return tuple(names) if names else None


def ts_imports(text: str) -> list[TsImport]:
    """Every import statement of a TypeScript/JavaScript source with the
    names it binds, in source order."""
    masked, strings = _masked(text)
    found: dict[int, TsImport] = {}
    for statement in _STATEMENTS:
        for match in statement.finditer(masked):
            quote = match.start(1)
            close = strings.get(quote)
            if close is None or close <= quote or quote in found:
                continue
            names = (
                _bound_names(masked[match.start() : quote])
                if statement is _FROM
                else None
            )
            found[quote] = TsImport(text[quote + 1 : close], names)
    return [found[q] for q in sorted(found)]


def ts_specifiers(text: str) -> list[str]:
    """Every module specifier a TypeScript/JavaScript source imports
    statically, re-exports, imports dynamically or requires, in source order.
    """
    return [i.specifier for i in ts_imports(text)]


def _quoted(text: str, strings: dict[int, int], quote: int) -> str | None:
    close = strings.get(quote)
    return text[quote + 1 : close] if close is not None and close > quote else None


def export_surface(text: str) -> ExportSurface:
    """What a TypeScript/JavaScript module exports, by name."""
    masked, strings = _masked(text)
    local = {m.group(1) for m in _LOCAL_DECLARATION.finditer(masked)}
    if _LOCAL_DEFAULT.search(masked):
        local.add("default")
    for match in _LOCAL_LIST.finditer(masked):
        local.update(bound for _, bound in _items(match.group(1)))
    named: list[tuple[int, tuple[str, str, str]]] = []
    for match in _NAMED_REEXPORT.finditer(masked):
        specifier = _quoted(text, strings, match.start(2))
        if specifier is not None:
            named += [
                (match.start(), (bound, source, specifier))
                for source, bound in _items(match.group(1))
            ]
    for match in _NAMESPACE_REEXPORT.finditer(masked):
        specifier = _quoted(text, strings, match.start(2))
        if specifier is not None:
            named.append((match.start(), (match.group(1), "*", specifier)))
    stars = [
        specifier
        for match in _STAR_REEXPORT.finditer(masked)
        if (specifier := _quoted(text, strings, match.start(1))) is not None
    ]
    return ExportSurface(
        local=frozenset(local),
        named=tuple(entry for _, entry in sorted(named, key=lambda n: n[0])),
        stars=tuple(stars),
    )


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
