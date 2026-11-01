"""This repository's own declaration (DESIGN.ARCH-ADHERENCE.md, G19: the
suite measures the suite with the suite, in its own gate; task-068).

load_declaration through the real git RepositoryPort over this checkout, at
the committed HEAD revision the gate reads, returns the layers, runtime,
records and radar adherence.toml declares, so the gate that judges this
repository judges adherence/ by layer. An uncommitted edit cannot pass it.
"""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.git import GitRepository
from adherence.application.load import load_declaration
from adherence.domain.declaration import Declaration, RecordPaths, Runtime
from adherence.domain.model import Layer
from adherence.domain.target import Head

# adherence/tests/integration/<this file> -> the repository root.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "adherence/src/adherence"


def test_load_declaration_of_this_repository_declares_adherence_by_layer() -> None:
    """Given this repository's checkout, When its declaration is loaded at HEAD
    through the git repository, Then adherence/ is declared by layer, under the adhere
    runtime, held to the Adherence records and the LMDE radar."""
    repository = GitRepository(str(REPOSITORY_ROOT))

    loaded = load_declaration(
        Head.at_revision("HEAD"), repository=repository, deadline=None
    )

    assert isinstance(loaded, Declaration)
    assert loaded.declared
    assert set(loaded.layers.globs) == {
        (Layer.DOMAIN, f"{PACKAGE}/domain/**"),
        (Layer.APPLICATION, f"{PACKAGE}/application/**"),
        (Layer.PORTS, f"{PACKAGE}/ports/**"),
        (Layer.ADAPTERS, f"{PACKAGE}/adapters/**"),
        (Layer.COMPOSITION_ROOT, f"{PACKAGE}/__init__.py"),
        (Layer.COMPOSITION_ROOT, f"{PACKAGE}/container.py"),
        (Layer.COMPOSITION_ROOT, f"{PACKAGE}/cli/**"),
        (Layer.TEST, "adherence/tests/*.py"),
        (Layer.TEST, "adherence/tests/unit/**"),
        (Layer.TEST, "adherence/tests/integration/**"),
    }
    assert loaded.runtimes == (Runtime("adhere", (f"{PACKAGE}/**",)),)
    assert loaded.records == RecordPaths(
        design="docs/design/DESIGN.ARCH-ADHERENCE.md",
        architecture="docs/design/ARCHITECTURE.ARCH-ADHERENCE.md",
    )
    assert loaded.radar == "lmde/TECH_RADAR.md"
    assert loaded.exemptions == ()
