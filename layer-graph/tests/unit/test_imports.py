"""Import extraction from TypeScript, Vue and Python source text."""

from layer_graph.domain.imports import (
    PythonImport,
    TsImport,
    export_surface,
    python_imports,
    reexport_specifiers,
    ts_imports,
    ts_specifiers,
    vue_scripts,
)


def test_ts_specifiers_reads_every_static_form() -> None:
    """Given import, export-from, side-effect, dynamic import and require, When
    scanned, Then every specifier is found once, in source order."""
    text = (
        "import a from './a';\n"
        'import type { B } from "./b";\n'
        "import {\n  c,\n  d,\n} from './cd';\n"
        "import './side';\n"
        "export * from './star';\n"
        "export { e } from './e';\n"
        "const f = await import('./f');\n"
        "const g = require('./g');\n"
    )
    assert ts_specifiers(text) == [
        "./a",
        "./b",
        "./cd",
        "./side",
        "./star",
        "./e",
        "./f",
        "./g",
    ]


def test_ts_specifiers_ignores_comments_and_strings() -> None:
    """Given import-like text inside comments and string literals, When
    scanned, Then none of it counts."""
    text = (
        "// import x from './line-comment';\n"
        "/* import y from './block-comment'; */\n"
        "const s = \"import z from './string'\";\n"
        "const t = `${1} // import w from './template'`;\n"
        "import real from './real';\n"
    )
    assert ts_specifiers(text) == ["./real"]


def test_ts_specifiers_export_without_from_is_not_an_import() -> None:
    """Given an export declaration followed later by an import, When scanned,
    Then only the import's specifier is found."""
    text = "export function f() { return 1 }\nimport g from './g'\n"
    assert ts_specifiers(text) == ["./g"]


def test_vue_scripts_returns_only_script_blocks() -> None:
    """Given a single-file component, When its scripts are taken, Then template
    text is left out and every script block is kept."""
    text = (
        "<template><p>import nope from 'nope'</p></template>\n"
        "<script lang=\"ts\">import a from './a'</script>\n"
        "<script setup lang=\"ts\">\nimport b from './b'\n</script>\n"
    )
    assert ts_specifiers(vue_scripts(text)) == ["./a", "./b"]


def test_python_imports_reads_absolute_from_and_relative() -> None:
    """Given import, from-import and relative from-import, When scanned, Then
    each module is found with its level and names."""
    text = (
        "import os, app.domain.rules\n"
        "from app.domain.model import Model, other\n"
        "from . import sibling\n"
        "from ..application.use import run\n"
    )
    assert python_imports(text) == [
        PythonImport("os", (), 0),
        PythonImport("app.domain.rules", (), 0),
        PythonImport("app.domain.model", ("Model", "other"), 0),
        PythonImport("", ("sibling",), 1),
        PythonImport("application.use", ("run",), 2),
    ]


def test_python_imports_unparseable_source_yields_nothing() -> None:
    """Given Python that does not parse, When scanned, Then no import is
    claimed."""
    assert python_imports("def broken(:\n") == []


def test_reexport_specifiers_reads_a_barrel() -> None:
    """Given a file of only re-exports in every form, When read, Then each
    re-exported specifier is returned in order."""
    text = (
        "// The public surface.\n"
        "export * from './a.ts';\n"
        "export * as b from './b';\n"
        "export { c, d as e } from './cd';\n"
        "export type { F } from './f';\n"
        "export type * from './g'\n"
    )
    assert reexport_specifiers(text) == ("./a.ts", "./b", "./cd", "./f", "./g")


def test_reexport_specifiers_file_with_other_code_is_not_a_barrel() -> None:
    """Given re-exports beside an import, a declaration or a local export,
    When read, Then the file is not a barrel."""
    assert reexport_specifiers("export * from './a';\nimport b from './b';\n") is None
    assert reexport_specifiers("export * from './a';\nexport const x = 1;\n") is None
    assert reexport_specifiers("export { a };\nexport * from './a';\n") is None


def test_reexport_specifiers_empty_file_is_not_a_barrel() -> None:
    """Given a file with only a comment, When read, Then it is not a barrel:
    a barrel re-exports something."""
    assert reexport_specifiers("// nothing here\n") is None


def test_ts_imports_names_what_a_statement_binds() -> None:
    """Given named, default, type, aliased, namespace and side-effect forms,
    When scanned, Then each statement carries the source-side names it binds,
    or None when it binds a whole module."""
    text = (
        "import { a, type B, c as d } from './x';\n"
        "import e, { f } from './y';\n"
        "import * as ns from './z';\n"
        "import './side';\n"
        "export { g as h } from './w';\n"
        "export * from './all';\n"
        "const m = require('./r');\n"
    )
    assert ts_imports(text) == [
        TsImport("./x", ("a", "B", "c")),
        TsImport("./y", ("default", "f")),
        TsImport("./z", None),
        TsImport("./side", None),
        TsImport("./w", ("g",)),
        TsImport("./all", None),
        TsImport("./r", None),
    ]


def test_export_surface_reads_local_and_reexported_names() -> None:
    """Given every local export form and every re-export form, When the
    surface is read, Then local names, named re-exports and stars are
    returned."""
    text = (
        "export function f() {}\n"
        "export async function g() {}\n"
        "export const h = 1;\n"
        "export let i = 1;\n"
        "export class J {}\n"
        "export abstract class K {}\n"
        "export interface L {}\n"
        "export type M = 1;\n"
        "export enum N { A }\n"
        "export const enum O { A }\n"
        "export namespace P {}\n"
        "export default 3;\n"
        "const q = 1, r = 2;\n"
        "export { q, r as s };\n"
        "export { t as u, default as V } from './t';\n"
        "export * as w from './w';\n"
        "export * from './star';\n"
    )
    surface = export_surface(text)
    assert surface.local == frozenset(
        {"f", "g", "h", "i", "J", "K", "L", "M", "N", "O", "P", "default", "q", "s"}
    )
    assert surface.named == (
        ("u", "t", "./t"),
        ("V", "default", "./t"),
        ("w", "*", "./w"),
    )
    assert surface.stars == ("./star",)
