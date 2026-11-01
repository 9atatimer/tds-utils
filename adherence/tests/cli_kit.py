"""Drive the adhere CLI through Click's runner with the composition root
bound to a fake behind every port: the judge kit's base and head, the
head adding a stubbed domain rule (so a judged change is lowered by an
introduced Stub), the working tree as the head. A test names the stage
and the rest of the command line; the CLI picks the format and the exit
status."""

from __future__ import annotations

import functools
from collections.abc import Sequence
from pathlib import Path

from click.testing import CliRunner, Result

from adherence.adapters.fakes import (
    FakeCodeModel,
    FakeComplexity,
    FakeDuplication,
    FakeRecords,
    FakeReportStore,
    FakeRepository,
    FakeReviews,
)
from adherence.adapters.inline_worker import InlineWorker
from adherence.cli.main import HOOK_BASE, main
from adherence.container import Container, Stage, build
from adherence.domain.declaration import DECLARATION_PATH
from adherence.domain.model import CodeLanguage, CodeModel
from adherence.domain.target import Base, Head
from adherence.ports.decision import DecisionPort
from tests.judge_kit import BASE, HEAD, RULES, passing_judge, stubbed, with_declaration
from tests.measure_kit import HEXAGON

STUBBED = b"\ndef tidy():\n    pass\n"
CLEAN = b"\ndef tidy():\n    return 1\n"
EDITED = b"\ndef tidy():\n    return 2\n"
JUDGE = ("judge", "--base", BASE.revision, "--head", HEAD.revision)


def faked(
    *,
    head: bytes = STUBBED,
    judge: DecisionPort | None = None,
    declaration: bytes = HEXAGON,
    now: float = 0.0,
) -> functools.partial[Container]:
    """The composition root with every port faked: the base (and HEAD, the
    hook's base) holds the rule implemented, the head, the staged index and
    the working tree the rule `head`: STUBBED a stub, CLEAN and EDITED a
    function that works. Both sides carry `declaration`. The repository's
    clock reads `now`, so a deadline at or before it has passed."""
    files = with_declaration({RULES: head}, declaration)
    base = with_declaration({RULES: CLEAN}, declaration)
    return functools.partial(
        build,
        repository=FakeRepository(
            {
                BASE: base,
                HEAD: files,
                Base(HOOK_BASE): base,
                Head.staged_index(): files,
                Head.working_tree(): files,
            },
            history={DECLARATION_PATH: (BASE.revision,)},
            now=now,
        ),
        reviews=FakeReviews(),
        analyzers={
            CodeLanguage.PYTHON: FakeCodeModel(
                CodeModel(),
                when={
                    STUBBED: stubbed(RULES, "tidy", 2),
                    CLEAN: stubbed(RULES, "tidy", 2, stub=None),
                    EDITED: stubbed(RULES, "tidy", 2, stub=None),
                },
            )
        },
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({}),
        judge=judge if judge is not None else passing_judge(),
        reports=FakeReportStore(),
        worker=InlineWorker(),
        environment={},
    )


class RecordingBuilder:
    """A composition root that records each stage it is asked to bind."""

    def __init__(self, builder: functools.partial[Container]) -> None:
        self._builder = builder
        self.stages: list[Stage] = []

    def __call__(self, stage: Stage, *, root: str) -> Container:
        self.stages.append(stage)
        return self._builder(stage, root=root)


def adhere(
    root: Path,
    *args: str,
    builder: functools.partial[Container] | RecordingBuilder | None = None,
) -> Result:
    """`adhere <args>` with `--root` given to the subcommand, over the
    faked composition root unless the test binds another."""
    command: Sequence[str] = [*args, "--root", str(root)]
    return CliRunner().invoke(main, command, obj=builder or faked())
