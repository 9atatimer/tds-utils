"""The Python CodeModelPort adapter over the fixture tree, one member at a
time (task-057), after the shared contract."""

from __future__ import annotations

from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.model import CodeModel, Layer, UnitKind
from adherence.ports.code_model import CodeModelPort
from tests import python_fixture
from tests.code_model_contract import CodeModelContract


class TestPythonCodeModel(CodeModelContract):
    def port(self) -> CodeModelPort:
        return PythonCodeModel()


def fixture_model() -> CodeModel:
    model = PythonCodeModel().model(
        python_fixture.sources(),
        python_fixture.declaration(),
        python_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


def test_units_are_each_definition_in_its_layer() -> None:
    """Given the fixture, When it is modelled, Then every function, method and
    class is a unit with its qualified symbol and the layer its file or its
    marker region puts it in."""
    units = {
        (u.path, u.symbol): (u.kind, u.layer)
        for u in fixture_model().units
        if u.kind is not UnitKind.FILE
    }

    assert units[("src/tool/domain/rules.py", "Order")] == (UnitKind.TYPE, Layer.DOMAIN)
    assert units[("src/tool/domain/rules.py", "Order.is_large")] == (
        UnitKind.FUNCTION,
        Layer.DOMAIN,
    )
    assert units[("src/tool/application/use.py", "close_order.helper")] == (
        UnitKind.FUNCTION,
        Layer.APPLICATION,
    )
    assert units[("src/tool/container.py", "build")] == (
        UnitKind.FUNCTION,
        Layer.COMPOSITION_ROOT,
    )
    assert units[("bin/onefile.py", "is_even")] == (UnitKind.FUNCTION, Layer.DOMAIN)
    assert units[("bin/onefile.py", "load")] == (UnitKind.FUNCTION, Layer.ADAPTERS)
    assert ("notes/uncovered.py", None) not in units


def test_regions_found_by_marker_are_in_the_model() -> None:
    """Given a marker file in the declaration, When it is modelled, Then its
    marker regions are part of the model."""
    regions = [(r.path, r.layer) for r in fixture_model().regions]

    assert regions == [("bin/onefile.py", Layer.DOMAIN), ("bin/onefile.py", Layer.ADAPTERS)]
