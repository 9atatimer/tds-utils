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
from adherence.adapters.python_ast import PythonCodeModel
from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.model import CodeLanguage
from adherence.ports.code_model import CodeModelPort
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


def build(
    stage: Stage,
    *,
    root: str,
    repository: RepositoryPort | None = None,
    analyzers: Mapping[CodeLanguage, CodeModelPort] | None = None,
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    TypeScript and JavaScript share one analyzer, so an import from one to
    the other resolves.
    """
    if analyzers is None:
        typescript = TypeScriptCodeModel()
        analyzers = {
            CodeLanguage.PYTHON: PythonCodeModel(),
            CodeLanguage.TYPESCRIPT: typescript,
            CodeLanguage.JAVASCRIPT: typescript,
            CodeLanguage.SHELL: ShellCodeModel(),
        }
    return Container(
        stage=stage,
        repository=repository if repository is not None else GitRepository(root),
        analyzers=analyzers,
    )
