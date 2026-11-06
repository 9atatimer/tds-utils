"""This repository's own declaration, read through the real git adapter: the
suite measures itself in its own gate (DESIGN.ARCH-ADHERENCE.md, Rollout;
Issue#600)."""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.git import GitRepository
from adherence.application.load import load_declaration
from adherence.domain.declaration import Declaration
from adherence.domain.model import Layer
from adherence.domain.target import Head

REPOSITORY = Path(__file__).resolve().parents[3]


def test_this_repository_declares_the_engine_by_layer() -> None:
    """Given this repository's working tree, When its declaration is loaded,
    Then it is declared, each engine package is in its layer, the two
    Adherence records are its records, the LMDE radar is its radar and
    `adhere` is its runtime."""
    loaded = load_declaration(
        Head.working_tree(), repository=GitRepository(str(REPOSITORY)), deadline=None
    )

    assert isinstance(loaded, Declaration), loaded
    assert loaded.declared
    globs = {pattern: layer for layer, pattern in loaded.layers.globs}
    assert globs["adherence/src/adherence/domain/**"] is Layer.DOMAIN
    assert globs["adherence/src/adherence/application/**"] is Layer.APPLICATION
    assert globs["adherence/src/adherence/ports/**"] is Layer.PORTS
    assert globs["adherence/src/adherence/adapters/**"] is Layer.ADAPTERS
    assert globs["adherence/src/adherence/container.py"] is Layer.COMPOSITION_ROOT
    assert globs["adherence/src/adherence/cli/**"] is Layer.COMPOSITION_ROOT
    assert globs["adherence/tests/unit/**"] is Layer.TEST
    assert "adherence/tests/**" not in globs, "fixtures are not the test layer"
    assert loaded.records is not None
    assert loaded.records.design == "docs/design/DESIGN.ARCH-ADHERENCE.md"
    assert loaded.records.architecture == "docs/design/ARCHITECTURE.ARCH-ADHERENCE.md"
    assert loaded.radar == "lmde/TECH_RADAR.md"
    assert [r.name for r in loaded.runtimes] == ["adhere"]
    assert not loaded.refused_exemptions
