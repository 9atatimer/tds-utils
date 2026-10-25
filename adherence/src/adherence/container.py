"""container.py -- the composition root of the adhere CLI.

The one module that constructs concrete adapters and binds them by stage
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Where it runs). It never
imports the fakes; a test passes them in through the overrides.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from adherence.adapters.git import GitRepository
from adherence.adapters.no_judge import NoJudge
from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.model import CodeLanguage
from adherence.ports.code_model import CodeModelPort
from adherence.ports.decision import DecisionPort
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
    analyzers: Mapping[CodeLanguage, CodeModelPort]
    judge: DecisionPort


def build(
    stage: Stage,
    *,
    root: str,
    repository: RepositoryPort | None = None,
    analyzers: Mapping[CodeLanguage, CodeModelPort] | None = None,
    judge: DecisionPort | None = None,
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    Every stage binds no_judge until the decide adapter lands (task-064);
    the judged checks read as coverage meanwhile.
    """
    return Container(
        stage=stage,
        repository=repository if repository is not None else GitRepository(root),
        analyzers=(
            analyzers
            if analyzers is not None
            else {CodeLanguage.PYTHON: PythonCodeModel()}
        ),
        judge=judge if judge is not None else NoJudge(),
    )
