"""`adhere judge` maps the verdict to the exit status per stage
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map: cli/main.py; DESIGN.ARCH-
ADHERENCE.md, Judging a change: lowered fails a gate; inconclusive and not
run never read as pass). Lowered and not run exit non-zero everywhere. In
the hook inconclusive exits zero, so the commit proceeds (The hook); on
the laptop and in the cloud, where an agent reads the report, it exits
zero too. At the gate, `ci`, an inconclusive verdict never reads as a
pass: it exits non-zero until the design's Q10 rules otherwise."""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.fakes import FakeDecision
from adherence.domain.questions import Unavailable
from tests.cli_kit import EDITED, JUDGE, STUBBED, adhere, faked

REVISION_STAGES = ("laptop", "ci", "cloud")
# A declaration in force that cannot be read: the run is not run.
UNREADABLE = b"[layers\n"


def _exit(root: Path, stage: str, **scripted: object) -> int:
    """The exit status of `adhere --stage <stage> judge` over the faked
    change, the hook judging the staged index and the rest the revisions."""
    judge = ("judge", "--staged") if stage == "hook" else JUDGE
    result = adhere(
        root,
        "--stage",
        stage,
        *judge,
        "--json",
        builder=faked(**scripted),  # type: ignore[arg-type]
    )
    return result.exit_code


def test_judge_lowered_exits_non_zero_in_every_stage(tmp_path: Path) -> None:
    """Given a change that introduces a stub, When it is judged in each
    stage, Then the exit status is non-zero."""
    for stage in ("hook", *REVISION_STAGES):
        assert _exit(tmp_path, stage, head=STUBBED) == 1, stage


def test_judge_not_run_exits_non_zero_in_every_stage(tmp_path: Path) -> None:
    """Given a declaration in force that cannot be read, When a change is
    judged in each stage, Then it is not run and exits non-zero."""
    for stage in ("hook", *REVISION_STAGES):
        assert _exit(tmp_path, stage, declaration=UNREADABLE) == 1, stage


def test_judge_held_exits_zero_in_every_stage(tmp_path: Path) -> None:
    """Given a change that introduces nothing and leaves nothing unresolved,
    When it is judged in each stage that judges revisions, Then it exits
    zero. (The hook asks no judged question, so a touched function is never
    held there; its inconclusive exit is below.)"""
    for stage in REVISION_STAGES:
        assert _exit(tmp_path, stage, head=EDITED) == 0, stage


def test_judge_inconclusive_fails_only_the_gate(tmp_path: Path) -> None:
    """Given a change whose touched unit a judged check could not ask about,
    the judge being unavailable, When it is judged, Then the hook, the
    laptop and the cloud exit zero, and ci, the gate, exits non-zero."""
    down = FakeDecision(Unavailable("the judge is down"))

    exits = {
        stage: _exit(tmp_path, stage, head=EDITED, judge=down)
        for stage in ("hook", *REVISION_STAGES)
    }

    assert exits == {"hook": 0, "laptop": 0, "cloud": 0, "ci": 1}
