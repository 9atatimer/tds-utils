"""container.py -- the composition root of the adhere CLI.

The one module that constructs concrete adapters and binds them by stage
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Where it runs). It never
imports the fakes; a test passes them in through the overrides.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from adherence.adapters.git import GitRepository
from adherence.ports.repository import RepositoryPort


class Stage(enum.Enum):
    """The places the one runtime runs in."""

    LAPTOP = "laptop"
    HOOK = "hook"
    CI = "ci"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class Container:
    """The ports bound for one stage."""

    stage: Stage
    repository: RepositoryPort


def build(
    stage: Stage, *, root: str, repository: RepositoryPort | None = None
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    """
    return Container(
        stage=stage,
        repository=repository if repository is not None else GitRepository(root),
    )
