"""The TypeScript and JavaScript CodeModelPort adapter over the fixture tree,
one member at a time (task-069), after the shared contract."""

from __future__ import annotations

import functools
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest

from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import (
    AccessKind,
    CodeModel,
    Definition,
    Layer,
    MemberKind,
    Parameter,
    ReferenceKind,
    Region,
    Signature,
    UnitKind,
)
from adherence.domain.parameters import Vocabulary
from adherence.ports.code_model import CodeModelPort
from tests import typescript_fixture
from tests.code_model_contract import TYPESCRIPT_SOURCES, CodeModelContract


class TestTypeScriptCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = TYPESCRIPT_SOURCES

    def port(self) -> CodeModelPort:
        return TypeScriptCodeModel()


# One model of the fixture for the whole module: building it spawns the
# analyzers, and the CodeModel is frozen, so sharing it cannot leak state
# between tests.
@functools.cache
def fixture_model() -> CodeModel:
    model = TypeScriptCodeModel().model(
        typescript_fixture.sources(),
        typescript_fixture.declaration(),
        typescript_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


def test_units_are_each_definition_in_its_layer() -> None:
    """Given the fixture, When it is modelled, Then every named function,
    method, class and interface is a unit with its qualified symbol and the
    layer its file puts it in; an anonymous callback is none."""
    units = {
        (u.path, u.symbol): (u.kind, u.layer)
        for u in fixture_model().units
        if u.kind is not UnitKind.FILE
    }

    rules, run = "lib/tool/rules.ts", "lib/tool/run.ts"
    assert units[(rules, "Order")] == (UnitKind.TYPE, Layer.DOMAIN)
    assert units[(rules, "Order.isLarge")] == (UnitKind.FUNCTION, Layer.DOMAIN)
    assert units[(run, "closeOrder.helper")] == (UnitKind.FUNCTION, Layer.APPLICATION)
    assert units[("lib/tool/ports.ts", "Store")] == (UnitKind.TYPE, Layer.PORTS)
    assert units[("lib/tool/schema.mjs", "isPlainObject")] == (
        UnitKind.FUNCTION,
        Layer.DOMAIN,
    )
    assert not any(path == "test/run.test.mjs" for path, _ in units)
    assert ("notes/uncovered.mjs", None) not in units


def test_regions_found_by_marker_are_in_the_model() -> None:
    """Given a one-file tool whose `// --- Section ---` markers the
    declaration names, When it is modelled, Then its marker regions are in
    the model and each function is in the layer of its region."""
    model = fixture_model()
    units = {(u.path, u.symbol): u.layer for u in model.units}

    assert [(r.path, r.layer) for r in model.regions] == [
        ("bin/tool.mjs", Layer.DOMAIN),
        ("bin/tool.mjs", Layer.ADAPTERS),
    ]
    assert units[("bin/tool.mjs", "isEven")] is Layer.DOMAIN
    assert units[("bin/tool.mjs", "load")] is Layer.ADAPTERS


def test_declared_line_regions_are_in_the_model() -> None:
    """Given a declaration that assigns a region by lines, When its file is
    modelled, Then that region is in the model beside the layer it gives,
    and a region of a file not handed over is not."""
    declaration = parse_declaration(
        b"[layers]\nregions = [\n"
        b'  { file = "m.ts", layer = "domain", lines = [1, 3] },\n'
        b'  { file = "absent.ts", layer = "domain", lines = [1, 2] },\n'
        b"]\n"
    )
    assert isinstance(declaration, Declaration)

    model = TypeScriptCodeModel().model(
        {"m.ts": b"function f(): number {\n  return 1;\n}\n"},
        declaration,
        typescript_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, CodeModel)
    assert model.regions == (Region("m.ts", 1, 3, Layer.DOMAIN),)
    assert [d.unit.layer for d in model.definitions] == [Layer.DOMAIN]


def _model_of(sources: dict[str, bytes]) -> CodeModel:
    model = TypeScriptCodeModel().model(
        sources,
        typescript_fixture.declaration(),
        typescript_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


@typescript_fixture.needs_cruiser
def test_imports_are_resolved_with_their_line_and_target_file() -> None:
    """Given relative, type-only, extensioned, package and node: imports,
    When the fixture is modelled, Then each is an edge to the module as
    written, with its line and text, and to its file when the file is a
    source."""
    edges = {
        (e.path, e.imported, e.line, e.imported_path)
        for e in fixture_model().imports
        if e.path in {"lib/tool/run.ts", "bin/tool.mjs", "test/run.test.mjs"}
    }

    run, rules = "lib/tool/run.ts", "lib/tool/rules.ts"
    assert edges == {
        (run, "node:timers/promises", 1, None),
        (run, "./rules", 2, rules),
        (run, "./rules", 3, rules),
        (run, "./ports", 4, "lib/tool/ports.ts"),
        ("bin/tool.mjs", "node:fs", 3, None),
        ("test/run.test.mjs", "node:test", 1, None),
        ("test/run.test.mjs", "node:assert/strict", 2, None),
        ("test/run.test.mjs", "../lib/tool/run.ts", 3, run),
    }
    [edge] = [e for e in fixture_model().imports if e.path == "bin/tool.mjs"]
    assert edge.text == "import { readFileSync } from 'node:fs';"


@typescript_fixture.needs_cruiser
def test_requires_reexports_and_dynamic_imports_are_edges() -> None:
    """Given a require, a re-export and a dynamic import, When they are
    modelled, Then each is an edge to the file it names."""
    model = _model_of(
        {
            "a.cjs": b"const b = require('./b.cjs');\n",
            "b.cjs": b"module.exports = {};\n",
            "c.mjs": b"export * from './b.cjs';\nconst a = await import('./a.cjs');\n",
        }
    )

    assert {(e.path, e.line, e.imported_path) for e in model.imports} == {
        ("a.cjs", 1, "b.cjs"),
        ("c.mjs", 1, "b.cjs"),
        ("c.mjs", 2, "a.cjs"),
    }


@typescript_fixture.needs_cruiser
def test_measured_code_is_never_run_even_as_the_analyzers_configuration(
    tmp_path: Path,
) -> None:
    """Given a measured dependency-cruiser configuration that would write a
    marker if it were loaded, When the sources are modelled, Then no marker
    is written and the imports are still resolved."""
    marker = tmp_path / "ran"
    payload = (
        f"require('node:fs').writeFileSync({str(marker)!r}, 'ran');\n"
        "module.exports = {};\n"
    ).encode()

    model = _model_of(
        {
            ".dependency-cruiser.cjs": payload,
            "a.mjs": b"import { b } from './b.mjs';\n",
            "b.mjs": b"export const b = 1;\n",
        }
    )

    assert not marker.exists(), "measured code ran"
    assert {(e.path, e.imported_path) for e in model.imports} == {
        (".dependency-cruiser.cjs", None),
        ("a.mjs", "b.mjs"),
    }


def _definition(path: str, symbol: str) -> Definition:
    [found] = [
        d
        for d in fixture_model().definitions
        if d.unit.path == path and d.unit.symbol == symbol
    ]
    return found


def test_definitions_carry_signature_bases_decorators_and_nesting() -> None:
    """Given functions, methods, a nested function, a decorated class and an
    interface, When the fixture is modelled, Then each definition carries its
    signature (an options object's members as keyword parameters), its return
    annotation, its bases and decorators, and whether a function encloses it."""
    rules, run = "lib/tool/rules.ts", "lib/tool/run.ts"
    classify = _definition(rules, "classify")
    close = _definition(run, "closeOrder")
    store = _definition("lib/tool/fs-store.ts", "FsStore")
    helper = _definition(run, "closeOrder.helper")
    method = _definition(rules, "Order.isLarge")

    assert classify.signature == Signature(
        parameters=(
            Parameter("order", "Order", keyword_only=False, has_default=False),
            Parameter("strict", "boolean", keyword_only=True, has_default=True),
        ),
        returns="string",
    )
    assert close.signature == Signature(
        parameters=(
            Parameter("order", "Order", keyword_only=False, has_default=False),
            Parameter("deps", "{ store: Store }", keyword_only=True, has_default=False),
        ),
        returns="Promise<string>",
    )
    assert _definition(rules, "Order").signature is None
    assert store.decorators == ("injectable()",)
    assert store.bases == ("Store",)
    assert (helper.parent, helper.nested) == ("closeOrder", True)
    assert (method.parent, method.nested) == ("Order", False)


def test_options_objects_are_keyword_parameters_by_the_vocabulary() -> None:
    """Given a destructured options object typed by name, a parameter the
    vocabulary names as an options object, a rest parameter and a bare arrow
    parameter, When they are modelled, Then the options object's members and
    the named parameter are keyword parameters and the rest are not."""
    source = (
        b"export function judge(\n"
        b"  change: Change, { repository, reviews = null }: Ports, ...rest: string[]\n"
        b"): void {}\n"
        b"function plain(change, ports) {}\n"
        b"const one = x => x;\n"
    )
    vocabulary = Vocabulary(regions={}, options_objects=frozenset({"ports"}))

    model = TypeScriptCodeModel().model(
        {"m.ts": source}, typescript_fixture.declaration(), vocabulary, None
    )

    assert isinstance(model, CodeModel)
    signatures = {d.unit.symbol: d.signature for d in model.definitions}
    assert signatures["judge"] == Signature(
        parameters=(
            Parameter("change", "Change", keyword_only=False, has_default=False),
            Parameter(
                "repository",
                'Ports["repository"]',
                keyword_only=True,
                has_default=False,
            ),
            Parameter(
                "reviews", 'Ports["reviews"]', keyword_only=True, has_default=True
            ),
            Parameter("...rest", "string[]", keyword_only=False, has_default=False),
        ),
        returns="void",
    )
    assert signatures["plain"] == Signature(
        parameters=(
            Parameter("change", None, keyword_only=False, has_default=False),
            Parameter("ports", None, keyword_only=True, has_default=False),
        ),
        returns=None,
    )
    assert signatures["one"] == Signature(
        parameters=(Parameter("x", None, keyword_only=False, has_default=False),),
        returns=None,
    )


def test_bodies_carry_their_text_stub_markers_and_sleeps() -> None:
    """Given a body that only throws NotImplementedError, an empty one, one
    that sleeps and an arrow whose body is an expression, When the fixture is
    modelled, Then each body carries its text, the placeholder it consists
    of, and the lines it sleeps on."""
    unfinished = _definition("lib/tool/rules.ts", "unfinished").body
    helper = _definition("lib/tool/run.ts", "closeOrder.helper").body
    close = _definition("lib/tool/run.ts", "closeOrder").body
    schema = "lib/tool/schema.mjs"

    assert unfinished.stub_markers == ("NotImplementedError",)
    assert helper.stub_markers == ("{}",)
    assert close.stub_markers == ()
    assert close.sleeps == (8,)
    assert "deps.store.save(order);" in close.text
    assert _definition(schema, "hasState").body.text == (
        "  return isPlainObject(record) && 'state' in record;"
    )
    assert _definition(schema, "isPlainObject").body.text == (
        "value !== null && typeof value === 'object'"
    )


def test_sleeps_and_stubs_come_from_the_vocabulary() -> None:
    """Given a vocabulary that counts `pause` as a sleep and only an empty
    body as a stub, When code is modelled with it, Then the model follows
    that vocabulary, not a fixed list."""
    vocabulary = Vocabulary(
        regions={}, sleeps=frozenset({"pause"}), stubs=frozenset({"{}"})
    )
    source = (
        b"function b() {\n"
        b"  pause(1);\n"
        b"  setTimeout(go, 1);\n"
        b"}\n"
        b"function c() {\n"
        b"  throw new NotImplementedError();\n"
        b"}\n"
        b"function d() {}\n"
    )

    model = TypeScriptCodeModel().model(
        {"m.ts": source}, typescript_fixture.declaration(), vocabulary, None
    )

    assert isinstance(model, CodeModel)
    bodies = {d.unit.symbol: d.body for d in model.definitions}
    assert bodies["b"].sleeps == (2,)
    assert (bodies["c"].stub_markers, bodies["d"].stub_markers) == ((), ("{}",))


def test_references_are_names_types_and_strings_but_not_specifiers() -> None:
    """Given code naming a chain through the environment, a module constant,
    a type and a model id, When the fixture is modelled, Then each name
    chain, type name and string literal is a reference in the definition it
    sits in; an import's module and a definition's own name are none."""
    references = {
        (r.path, r.within, r.kind, r.text) for r in fixture_model().references
    }

    save = ("lib/tool/fs-store.ts", "FsStore.save")
    assert (*save, ReferenceKind.STRING, "claude-opus") in references
    assert (*save, ReferenceKind.NAME, "process.env.HOME") in references
    assert (*save, ReferenceKind.NAME, "process") not in references
    assert (
        "lib/tool/rules.ts",
        "Order.isLarge",
        ReferenceKind.NAME,
        "LIMIT",
    ) in references
    assert ("lib/tool/run.ts", "closeOrder", ReferenceKind.NAME, "Store") in references
    assert not any(r[3] in {"./rules", "node:fs"} for r in references)
    assert not any(
        r[0] == "lib/tool/run.ts" and r[3] == "closeOrder" for r in references
    )


def test_calls_name_their_callee_and_the_definition_they_sit_in() -> None:
    """Given function, method and constructor calls, and a chain broken over
    lines, When they are modelled, Then each call names its callee as
    written (the chain joined up), its line, and the definition it sits in."""
    calls = {(c.path, c.within, c.callee, c.line) for c in fixture_model().calls}
    chained = _model_of({"m.ts": b"function f() {\n  a\n    .b\n    .c(1);\n}\n"})

    run = "lib/tool/run.ts"
    assert (run, "closeOrder", "sleep", 8) in calls
    assert (run, "closeOrder", "deps.store.save", 9) in calls
    assert (run, "closeOrder", "classify", 13) in calls
    assert ("lib/tool/rules.ts", "unfinished", "NotImplementedError", 21) in calls
    assert [(c.within, c.callee, c.line) for c in chained.calls] == [("f", "a.b.c", 2)]


def test_accesses_are_environment_reads_and_globals() -> None:
    """Given a read of the environment and a write through globalThis, When
    the fixture is modelled, Then each is an access of its kind in the
    definition it sits in."""
    accesses = {(a.path, a.within, a.kind, a.target) for a in fixture_model().accesses}

    assert accesses == {
        (
            "lib/tool/fs-store.ts",
            "FsStore.save",
            AccessKind.ENVIRONMENT,
            "process.env.HOME",
        ),
        ("bin/tool.mjs", "load", AccessKind.GLOBAL, "globalThis.counter"),
    }


def test_an_environment_read_by_subscript_or_destructuring_is_an_access() -> None:
    """Given `process.env[...]` and `const { A } = process.env`, When they
    are modelled, Then each is an environment access of process.env."""
    model = _model_of(
        {"m.mjs": b"const a = process.env['A'];\nconst { B } = process.env;\n"}
    )

    assert sorted((a.line, a.kind, a.target) for a in model.accesses) == [
        (1, AccessKind.ENVIRONMENT, "process.env"),
        (2, AccessKind.ENVIRONMENT, "process.env"),
    ]


def test_writes_are_field_assignments_with_the_unit_that_makes_them() -> None:
    """Given a use case assigning a domain value's field, a constructor
    assigning its own, a global incremented in place, and an update and a
    logical assignment, When they are modelled, Then each is a write of that
    field, on that object, by the definition it sits in."""
    writes = {(w.path, w.within, w.target, w.field) for w in fixture_model().writes}
    updated = _model_of({"m.ts": b"function f(o) {\n  o.n++;\n  o.m ||= 1;\n}\n"})

    assert writes == {
        ("lib/tool/run.ts", "closeOrder", "order", "status"),
        ("lib/tool/fs-store.ts", "FsStore.constructor", "this", "opened"),
        ("bin/tool.mjs", "load", "globalThis", "counter"),
    }
    assert [(w.line, w.target, w.field) for w in updated.writes] == [
        (2, "o", "n"),
        (3, "o", "m"),
    ]


def test_conditionals_name_their_discriminant() -> None:
    """Given a branch on a value's field, When the fixture is modelled, Then
    the conditional names the expression it discriminates on, its line and
    the definition it sits in."""
    conditionals = {
        (c.path, c.within, c.discriminant, c.line) for c in fixture_model().conditionals
    }

    assert conditionals == {("lib/tool/rules.ts", "classify", "order.status", 14)}


def test_conditionals_see_through_logic_switches_and_instanceof() -> None:
    """Given branches joined by `&&` and `!`, a switch, an instanceof test
    and a ternary on a call, When they are modelled, Then each names what it
    discriminates on."""
    source = (
        b"function f(x, y, kind) {\n"
        b"  if (x.a === 1 && !y) {}\n"
        b"  switch (kind) { case 1: break; }\n"
        b"  if (x instanceof Foo) {}\n"
        b"  const v = isReady(x) ? 1 : 2;\n"
        b"}\n"
    )

    model = _model_of({"m.mjs": source})

    assert sorted((c.line, c.discriminant) for c in model.conditionals) == [
        (2, "x.a"),
        (2, "y"),
        (3, "kind"),
        (4, "x"),
        (5, "isReady"),
    ]


def test_members_are_each_types_fields_and_methods() -> None:
    """Given a class with fields, a class with a parameter property and a
    field set in its constructor, and an interface, When the fixture is
    modelled, Then each type's fields (declared, a parameter property, or
    assigned on this) and methods are its members."""
    members = {(m.path, m.owner, m.name, m.kind) for m in fixture_model().members}

    rules, ports, fs = (
        "lib/tool/rules.ts",
        "lib/tool/ports.ts",
        "lib/tool/fs-store.ts",
    )
    assert members == {
        (rules, "Order", "total", MemberKind.FIELD),
        (rules, "Order", "status", MemberKind.FIELD),
        (rules, "Order", "isLarge", MemberKind.METHOD),
        (ports, "Store", "save", MemberKind.METHOD),
        (fs, "FsStore", "constructor", MemberKind.METHOD),
        (fs, "FsStore", "root", MemberKind.FIELD),
        (fs, "FsStore", "opened", MemberKind.FIELD),
        (fs, "FsStore", "save", MemberKind.METHOD),
    }


def test_an_object_type_alias_has_members_and_a_parameter_type_none() -> None:
    """Given a type alias of an object type and a method whose parameter is
    typed by an object type, When they are modelled, Then the alias's
    members are its own and the parameter's type adds none to the class."""
    source = (
        b"type Ports = { save(o: O): void; name: string };\n"
        b"class C {\n"
        b"  m(o: { x: number }): void {}\n"
        b"}\n"
    )

    model = _model_of({"m.ts": source})

    assert {(m.owner, m.name, m.kind) for m in model.members} == {
        ("Ports", "save", MemberKind.METHOD),
        ("Ports", "name", MemberKind.FIELD),
        ("C", "m", MemberKind.METHOD),
    }


def test_test_cases_carry_their_calls_and_assertions() -> None:
    """Given node:test and Vitest-style tests, one of which only calls, inside
    and outside a describe block, When the fixture is modelled, Then each
    test case carries its title, what it calls and what it asserts, so a test
    that cannot fail is visible; the describe block is no test."""
    cases = {
        (t.path, t.symbol, t.line, t.calls, t.assertions)
        for t in fixture_model().test_cases
    }

    path = "test/run.test.mjs"
    assert cases == {
        (
            path,
            "closeOrder saves",
            5,
            ("closeOrder", "order"),
            ("assert.equal(await closeOrder(order(), { store }), 'pending')",),
        ),
        (path, "nothing", 9, ("closeOrder",), ()),
        (path, "is large", 14, ("isLarge",), ("expect(isLarge(5)).toBe(true)",)),
    }


def test_tests_and_assertions_come_from_the_vocabulary() -> None:
    """Given a vocabulary whose test function is `spec` and whose assertion
    is `check`, When code is modelled with it, Then only a `spec` call is a
    test case and only a `check` call is its assertion."""
    vocabulary = Vocabulary(
        regions={}, tests=frozenset({"spec"}), assertions=frozenset({"check"})
    )
    source = b"spec('a', () => {\n  check(run());\n});\ntest('b', () => run());\n"

    model = TypeScriptCodeModel().model(
        {"t.mjs": source}, typescript_fixture.declaration(), vocabulary, None
    )

    assert isinstance(model, CodeModel)
    assert [(t.symbol, t.calls, t.assertions) for t in model.test_cases] == [
        ("a", ("run",), ("check(run())",))
    ]


def test_a_file_that_does_not_parse_is_unparsed_and_the_rest_modelled() -> None:
    """Given a file with a syntax error and a file that is not UTF-8 beside a
    good one, When they are modelled, Then each of the two is Unparsed with
    its reason and holds no unit, and the good file is modelled."""
    model = _model_of(
        {
            "bad.ts": b"export const x = (;\n",
            "fine.ts": b"export function f(): number {\n  return 1;\n}\n",
            "latin.mjs": b"const s = '\xe9';\n",
        }
    )

    reasons = {u.path: u.reason for u in model.unparsed}
    assert sorted(reasons) == ["bad.ts", "latin.mjs"]
    assert "syntax error at line 1" in reasons["bad.ts"]
    assert "not utf-8" in reasons["latin.mjs"]
    assert {u.path for u in model.units} == {"fine.ts"}
    assert [d.unit.symbol for d in model.definitions] == ["f"]


def test_a_file_missing_a_closing_token_is_unparsed_alone() -> None:
    """Given files the parser repairs by inserting a missing token (an
    unclosed block, parameter list, call and for-of header) beside a good
    one, When they are modelled, Then each repaired file is Unparsed with
    the line of its missing token and holds no unit, and the good file is
    modelled."""
    model = _model_of(
        {
            "block.ts": b"function f() {\n  return 1;\n",
            "call.mjs": b"const a = 1;\ng(a, 2;\n",
            "loop.ts": b"for (const k of ks {\n  use(k);\n}\n",
            "params.ts": b"function g(x {\n  return x;\n}\n",
            "fine.ts": b"export function ok(): number {\n  return 1;\n}\n",
        }
    )

    reasons = {u.path: u.reason for u in model.unparsed}
    assert sorted(reasons) == ["block.ts", "call.mjs", "loop.ts", "params.ts"]
    assert "syntax error at line 2" in reasons["block.ts"]
    assert "syntax error at line 2" in reasons["call.mjs"]
    assert "syntax error at line 1" in reasons["loop.ts"]
    assert "syntax error at line 1" in reasons["params.ts"]
    assert {u.path for u in model.units} == {"fine.ts"}
    assert [d.unit.symbol for d in model.definitions] == ["ok"]


def test_a_file_nested_past_the_walk_is_unparsed_and_the_rest_modelled() -> None:
    """Given a file that parses but nests deeper than the analyzer can walk,
    When it is modelled with another file, Then that file is Unparsed and
    the other is modelled; the run does not end."""
    deep = b"if (" + b" && ".join([b"a"] * 1200) + b") {}\n"

    model = _model_of(
        {"deep.ts": deep, "fine.ts": b"function f(): number {\n  return 1;\n}\n"}
    )

    assert [u.path for u in model.unparsed] == ["deep.ts"]
    assert any(d.unit.symbol == "f" for d in model.definitions)


IMPORTING = {
    "a.mjs": b"import { b } from './b.mjs';\nexport function f() {}\n",
    "b.mjs": b"export const b = 1;\n",
}


def test_without_ast_grep_every_source_is_unparsed_with_the_reason(
    tmp_path: Path,
) -> None:
    """Given no ast-grep where the adapter looks for it, When sources are
    modelled, Then each is Unparsed with a reason naming ast-grep, and
    nothing reads as clean."""
    model = TypeScriptCodeModel(ast_grep=tmp_path / "ast-grep").model(
        IMPORTING, typescript_fixture.declaration(), typescript_fixture.VOCABULARY, None
    )

    assert isinstance(model, CodeModel)
    assert model.units == ()
    assert [u.path for u in model.unparsed] == ["a.mjs", "b.mjs"]
    assert all("ast-grep" in u.reason for u in model.unparsed)


@typescript_fixture.needs_node
def test_without_dependency_cruiser_every_file_is_unparsed_with_its_facts(
    tmp_path: Path,
) -> None:
    """Given no dependency-cruiser where the adapter looks for it, When
    sources that import are modelled, Then their facts stand, no import
    resolves, and each file is Unparsed with a reason naming the tool."""
    model = TypeScriptCodeModel(cruiser=tmp_path / "dependency-cruiser.mjs").model(
        IMPORTING, typescript_fixture.declaration(), typescript_fixture.VOCABULARY, None
    )

    assert isinstance(model, CodeModel)
    assert [d.unit.symbol for d in model.definitions] == ["f"]
    assert [(e.path, e.imported_path) for e in model.imports] == [("a.mjs", None)]
    assert [u.path for u in model.unparsed] == ["a.mjs", "b.mjs"]
    assert all("dependency-cruiser" in u.reason for u in model.unparsed)


def test_without_node_every_file_is_unparsed_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a PATH with no node on it, When sources that import are
    modelled, Then each file is Unparsed with a reason naming node."""
    monkeypatch.setenv("PATH", str(tmp_path))

    model = _model_of(IMPORTING)

    assert [u.path for u in model.unparsed] == ["a.mjs", "b.mjs"]
    assert all("node" in u.reason for u in model.unparsed)


@pytest.mark.parametrize("passes_after", [1, 2], ids=["ast-grep", "cruiser"])
def test_model_past_the_deadline_between_analyzers_times_out(passes_after: int) -> None:
    """Given a deadline that passes once the run has started, before ast-grep
    or before dependency-cruiser runs, When sources that import are
    modelled, Then the answer is TimedOut rather than an overrun or a
    partial model."""
    readings = iter([0.0] * passes_after + [10.0] * 5)

    answer = TypeScriptCodeModel(clock=lambda: next(readings, 99.0)).model(
        IMPORTING,
        typescript_fixture.declaration(),
        typescript_fixture.VOCABULARY,
        Deadline(epoch_seconds=5.0),
    )

    assert isinstance(answer, TimedOut)


def test_a_path_that_leaves_the_repository_is_unparsed_and_never_written(
    tmp_path: Path,
) -> None:
    """Given sources keyed by a path climbing out of the repository and by an
    absolute path, When they are modelled, Then each is Unparsed with the
    reason, nothing is written where it points, and the rest is modelled."""
    climbing = f"../../adhere-escape-{uuid.uuid4().hex}.ts"
    absolute = tmp_path / "absolute.ts"

    model = _model_of(
        {
            climbing: b"export const x = 1;\n",
            str(absolute): b"export const y = 2;\n",
            "fine.ts": b"export function f(): number {\n  return 1;\n}\n",
        }
    )

    assert not Path(tempfile.gettempdir(), Path(climbing).name).exists()
    assert not absolute.exists()
    reasons = {u.path: u.reason for u in model.unparsed}
    assert set(reasons) == {climbing, str(absolute)}
    assert all("leaves the repository" in r for r in reasons.values())
    assert {u.path for u in model.units} == {"fine.ts"}
