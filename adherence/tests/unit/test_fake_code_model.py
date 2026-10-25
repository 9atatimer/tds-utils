"""The fake CodeModelPort passes the same contract as the Python adapter."""

from __future__ import annotations

from adherence.adapters.fakes import FakeCodeModel
from adherence.ports.code_model import CodeModelPort
from tests.code_model_contract import CodeModelContract


class TestFakeCodeModel(CodeModelContract):
    def port(self) -> CodeModelPort:
        return FakeCodeModel()
