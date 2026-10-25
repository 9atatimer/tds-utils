"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.domain.model import CodeModel, Layer, UnitKind
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
