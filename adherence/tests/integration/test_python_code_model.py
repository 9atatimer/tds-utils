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

    assert regions == [
        ("bin/onefile.py", Layer.DOMAIN),
        ("bin/onefile.py", Layer.ADAPTERS),
    ]


def test_imports_are_resolved_with_their_line_and_target_file() -> None:
    """Given package, relative, plain-script and standard-library imports,
    When the fixture is modelled, Then each is an edge to the module it
    resolves to, with its line, and to its file when the file is a source."""
    edges = {
        (e.path, e.imported, e.line, e.imported_path)
        for e in fixture_model().imports
        if e.path
        in {
            "src/tool/application/use.py",
            "src/tool/container.py",
            "tests/test_use.py",
            "bin/onefile.py",
        }
    }

    assert edges == {
        ("src/tool/application/use.py", "time", 1, None),
        (
            "src/tool/application/use.py",
            "tool.domain.rules",
            3,
            "src/tool/domain/rules.py",
        ),
        (
            "src/tool/application/use.py",
            "tool.domain.rules",
            4,
            "src/tool/domain/rules.py",
        ),
        (
            "src/tool/application/use.py",
            "tool.ports.store",
            5,
            "src/tool/ports/store.py",
        ),
        (
            "src/tool/container.py",
            "tool.adapters.fs_store",
            1,
            "src/tool/adapters/fs_store.py",
        ),
        (
            "src/tool/container.py",
            "tool.application.use",
            3,
            "src/tool/application/use.py",
        ),
        ("tests/test_use.py", "tool.application.use", 1, "src/tool/application/use.py"),
        ("bin/onefile.py", "json", 3, None),
    }


def test_imports_resolve_against_the_sources_never_the_engine() -> None:
    """Given a measured package named like the engine's own, When it is
    modelled, Then its imports resolve inside the sources handed over."""
    sources = {
        "src/adherence/__init__.py": b"",
        "src/adherence/a.py": b"from adherence import b\n",
        "src/adherence/b.py": b"",
    }
    model = PythonCodeModel().model(
        sources, python_fixture.declaration(), python_fixture.VOCABULARY, None
    )

    assert isinstance(model, CodeModel)
    assert {(e.path, e.imported_path) for e in model.imports} == {
        ("src/adherence/a.py", "src/adherence/b.py")
    }
