"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

from collections.abc import Mapping

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.ports.code_model import CodeModelPort
from tests.code_model_contract import SHELL_SOURCES, CodeModelContract


class TestShellCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = SHELL_SOURCES

    def port(self) -> CodeModelPort:
        return ShellCodeModel()
