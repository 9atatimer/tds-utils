"""The TypeScript and JavaScript CodeModelPort adapter over the fixture tree,
one member at a time (task-069), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping

from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import CodeModel, Layer, Region, UnitKind
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
