"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.domain.model import CodeModel, Definition, Layer, Region, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.ports.code_model import CodeModelPort
from tests import shell_fixture
from tests.code_model_contract import SHELL_SOURCES, CodeModelContract


class TestShellCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = SHELL_SOURCES

    def port(self) -> CodeModelPort:
        return ShellCodeModel()


# One model of the fixture for the whole module: building it spawns
# ast-grep, and the CodeModel is frozen, so sharing it cannot leak state
# between tests.
@functools.cache
def fixture_model() -> CodeModel:
    model = ShellCodeModel().model(
        shell_fixture.sources(),
        shell_fixture.declaration(),
        shell_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


def _model_of(sources: dict[str, bytes]) -> CodeModel:
    model = ShellCodeModel().model(
        sources, shell_fixture.declaration(), shell_fixture.VOCABULARY, None
    )
    assert isinstance(model, CodeModel), model
    return model


def test_units_are_each_function_in_its_layer() -> None:
    """Given the fixture, When it is modelled, Then every function, in
    either declaration form, is a unit with its lines and the layer its file
    or region puts it in, and a nested function carries its parent."""
    units = {
        (u.path, u.symbol): (u.kind, u.start, u.end, u.layer)
        for u in fixture_model().units
        if u.kind is not UnitKind.FILE
    }

    release = "bin/release.sh"
    assert units[(release, "fetch_line")] == (UnitKind.FUNCTION, 8, 10, Layer.ADAPTERS)
    assert units[(release, "head_of")] == (UnitKind.FUNCTION, 12, 14, Layer.ADAPTERS)
    assert units[(release, "release_unit")] == (
        UnitKind.FUNCTION,
        21,
        29,
        Layer.APPLICATION,
    )
    assert units[(release, "main")] == (
        UnitKind.FUNCTION,
        37,
        39,
        Layer.COMPOSITION_ROOT,
    )
    assert units[("lib/checks.sh", "is_ancestor")][3] is Layer.DOMAIN
    assert units[("test/release_test.sh", "test_release_needs_a_unit")][3] is (
        Layer.TEST
    )
    assert not any(path == "notes/uncovered.sh" for path, _ in units)

    nested = _model_of({"m.sh": b"outer() {\n    inner() { :; }\n    inner\n}\n"})
    assert [(d.unit.symbol, d.parent, d.nested) for d in nested.definitions] == [
        ("outer", None, False),
        ("outer.inner", "outer", True),
    ]


def test_regions_found_by_marker_are_in_the_model() -> None:
    """Given a script whose `# --- Section ---` markers the declaration
    names, When it is modelled, Then each marker's region is in the model,
    from its marker to the line before the next, in the layer the
    vocabulary maps it to."""
    assert fixture_model().regions == (
        Region("bin/release.sh", 7, 19, Layer.ADAPTERS),
        Region("bin/release.sh", 20, 35, Layer.APPLICATION),
        Region("bin/release.sh", 36, 41, Layer.COMPOSITION_ROOT),
    )


def _definition(path: str, symbol: str) -> Definition:
    [found] = [
        d
        for d in fixture_model().definitions
        if (d.unit.path, d.unit.symbol) == (path, symbol)
    ]
    return found


def test_bodies_carry_their_text_and_stub_markers() -> None:
    """Given a function whose body is only the `:` placeholder beside a
    comment, one that runs `:` for its expansion before real work, and an
    ordinary one, When the fixture is modelled, Then each body carries its
    text, and only the first is the placeholder it consists of."""
    rollback = _definition("bin/release.sh", "rollback").body
    ancestor = _definition("lib/checks.sh", "is_ancestor").body
    fetch = _definition("bin/release.sh", "fetch_line").body

    assert rollback.stub_markers == (":",)
    assert ancestor.stub_markers == ()
    assert fetch.stub_markers == ()
    assert fetch.text == '    git fetch --quiet origin "$1"'
    assert "git merge-base --is-ancestor" in ancestor.text


def test_stubs_come_from_the_vocabulary() -> None:
    """Given a vocabulary that counts no placeholder as a stub, When a
    `:`-only body is modelled with it, Then the body carries no stub marker."""
    model = ShellCodeModel().model(
        {"m.sh": b"later() {\n    :\n}\n"},
        shell_fixture.declaration(),
        Vocabulary(regions={}),
        None,
    )

    assert isinstance(model, CodeModel)
    assert [d.body.stub_markers for d in model.definitions] == [()]
