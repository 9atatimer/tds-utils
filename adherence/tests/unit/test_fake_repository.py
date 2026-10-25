"""The fake RepositoryPort passes the same contract as the git adapter."""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.fakes import FakeRepository
from adherence.domain.target import Base, Head
from adherence.ports.repository import RepositoryPort
from tests.repository_contract import Files, RepositoryContract


class TestFakeRepository(RepositoryContract):
    def repository_with(
        self,
        tmp_path: Path,
        *,
        base: Files,
        staged: Files,
        working: Files,
    ) -> tuple[RepositoryPort, Base]:
        at_base = Base("0" * 40)
        files = {
            at_base: dict(base),
            Head.at_revision(at_base.revision): dict(base),
            Head.staged_index(): {**base, **staged},
            Head.working_tree(): {**base, **staged, **working},
        }
        return FakeRepository(files), at_base
