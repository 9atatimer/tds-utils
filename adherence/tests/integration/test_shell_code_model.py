"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.domain.model import Body, CodeModel, Layer, UnitKind
from adherence.ports.code_model import CodeModelPort
from tests import shell_fixture
from tests.code_model_contract import SHELL_SOURCES, CodeModelContract

TOOL = "bin/tool"


class TestShellCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = SHELL_SOURCES

    def port(self) -> CodeModelPort:
        return ShellCodeModel()


# One model of the fixture for the whole module: building it spawns the
# analyzer, and the CodeModel is frozen, so sharing it cannot leak state
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


def test_functions_are_units_in_the_layer_of_their_marker_region() -> None:
    """Given a one-file tool whose `# --- Section ---` markers the
    declaration names, When it is modelled, Then its marker regions are in
    the model and each function is a unit in the layer of its region, one
    before the first marker in none."""
    model = fixture_model()
    units = {
        (u.path, u.symbol): (u.kind, u.layer)
        for u in model.units
        if u.kind is not UnitKind.FILE
    }

    assert [(r.path, r.layer) for r in model.regions] == [
        (TOOL, Layer.ADAPTERS),
        (TOOL, Layer.APPLICATION),
        (TOOL, Layer.COMPOSITION_ROOT),
    ]
    function = UnitKind.FUNCTION
    assert units[(TOOL, "die")] == (function, None)
    assert units[(TOOL, "head_of")] == (function, Layer.ADAPTERS)
    assert units[(TOOL, "pending")] == (function, Layer.ADAPTERS)
    assert units[(TOOL, "advance")] == (function, Layer.APPLICATION)
    assert units[(TOOL, "main")] == (function, Layer.COMPOSITION_ROOT)
    assert units[("lib/common.sh", "log_line")] == (function, Layer.ADAPTERS)


def test_every_command_is_a_call_with_its_function() -> None:
    """Given the fixture, When it is modelled, Then every command run is a
    call to its name as written, in a pipeline or a substitution alike,
    with the function it sits in, or none at the top."""
    calls = {(c.within, c.callee, c.line) for c in fixture_model().calls}

    assert {
        ("head_of", "git", 17),
        ("check_clean", "git", 32),
        ("check_clean", "head", 32),
        ("check_clean", "die", 33),
        ("advance", "check_clean", 37),
        ("advance", "command", 40),
        ("advance", "head_of", 40),
        (None, "source", 9),
        (None, "main", 57),
    } <= calls


def test_bodies_are_their_text_with_stub_and_sleep() -> None:
    """Given functions that do work, wait, and are nothing but a no-op,
    When the fixture is modelled, Then each body is its text inside the
    braces, the no-op the Vocabulary counts is its stub marker, and a
    sleep's line is where it waits."""
    bodies = {
        d.unit.symbol: d.body
        for d in fixture_model().definitions
        if d.unit.path == TOOL
    }

    assert bodies["head_of"] == Body('    git -C "$1" rev-parse HEAD', (), ())
    assert bodies["wait_for_lock"] == Body("    sleep 1", (), (22,))
    assert bodies["pending"] == Body(":;", (":",), ())
    assert bodies["die"] == Body('echo "tool: $*" >&2; exit 1;', (), ())
