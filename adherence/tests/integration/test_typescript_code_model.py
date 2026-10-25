"""The TypeScript and JavaScript CodeModelPort adapter over the fixture tree,
one member at a time (task-069), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping

from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.model import CodeModel, Layer, UnitKind
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
