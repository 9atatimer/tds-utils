"""ports/code_model.py -- CodeModelPort: one analyzer per language.

The use case reads the sources through RepositoryPort and hands over
their bytes; the analyzer turns them into the language-neutral CodeModel,
each unit in the layer the declaration gives it (ARCHITECTURE.ARCH-
ADHERENCE.md, Seams and Mechanism > Measurement).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Vocabulary


class CodeModelPort(Protocol):
    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        """The CodeModel of the sources, keyed by repository path."""
        ...
