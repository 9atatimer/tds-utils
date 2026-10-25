"""The TypeScript and JavaScript CodeModelPort adapter over the fixture tree,
one member at a time (task-069), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path

from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import (
    CodeModel,
    Definition,
    Layer,
    Parameter,
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
