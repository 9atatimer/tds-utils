"""load_declaration (ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface).

Driven by its signature with a fake RepositoryPort behind it: the
load_declaration halves of "An undeclared repository is measured" and
"An unreadable declaration is not run". The measure halves are task-058.
"""

from __future__ import annotations

from adherence.adapters.fakes import FakeRepository
from adherence.application.load import load_declaration
from adherence.domain.declaration import Declaration
from adherence.domain.target import Head

HEAD = Head.working_tree()


def test_load_declaration_with_no_declaration_returns_none() -> None:
    """Given a repository with no adherence.toml, When its declaration is loaded,
    Then it is Declaration.none, so the run measures it as undeclared."""
    repository = FakeRepository({HEAD: {"src/tool.py": b"print('hi')\n"}})

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert loaded is Declaration.none
    assert not loaded.declared
