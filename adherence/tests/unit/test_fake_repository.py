"""The fake RepositoryPort passes the same contract as the git adapter."""

from __future__ import annotations

from collections.abc import Collection
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
        deleted: Collection[str] = (),
    ) -> tuple[RepositoryPort, Base]:
        at_base = Base("0" * 40)
        staged_index = {
            p: data for p, data in {**base, **staged}.items() if p not in deleted
        }
        files = {
            at_base: dict(base),
            Head.at_revision(at_base.revision): dict(base),
            Head.staged_index(): staged_index,
            Head.working_tree(): {**staged_index, **working},
        }
        return FakeRepository(files), at_base
