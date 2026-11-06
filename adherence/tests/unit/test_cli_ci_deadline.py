"""CI out of time is coverage, at the entry point (DESIGN.ARCH-ADHERENCE.md,
Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Seams: Deadline -- CI sets it
from the job's remaining time; Module map: cli/main.py computes the
Deadline for the hook and for CI). The job says how much time it has left
with `--time-left`; the CLI turns it into the Deadline every deadline-bound
port is given."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.cli_kit import JUDGE, adhere, faked

# A clock far past any deadline the CLI can compute today.
LATE = 1e12


def test_ci_judge_past_the_jobs_time_is_coverage(tmp_path: Path) -> None:
    """Given a ci job with a minute left and ports whose clock reads past
    it, When `adhere --stage ci judge --time-left 60` runs, Then the run
    ends at the deadline: the unfinished checks are coverage, the verdict
    is inconclusive, and the gate exits zero: inconclusive never fails a
    gate."""
    result = adhere(
        tmp_path,
        "--stage",
        "ci",
        *JUDGE,
        "--time-left",
        "60",
        "--json",
        builder=faked(now=LATE),
    )

    document = json.loads(result.output)
    assert document["verdict"] == "inconclusive", result.output
    assert any("timed out" in c["reason"] for c in document["coverage"])
    assert result.exit_code == 0


def test_ci_judge_with_no_time_left_given_is_unbounded(tmp_path: Path) -> None:
    """Given the same ports and no --time-left, When `adhere --stage ci
    judge` runs, Then no deadline is set and the stub is found and lowers."""
    result = adhere(
        tmp_path, "--stage", "ci", *JUDGE, "--json", builder=faked(now=LATE)
    )

    assert json.loads(result.output)["verdict"] == "lowered", result.output


def test_time_left_outside_ci_is_refused(tmp_path: Path) -> None:
    """Given --time-left on the laptop, When `adhere judge` runs, Then the
    command line is refused: only the gate's job has a remaining time."""
    result = adhere(tmp_path, *JUDGE, "--time-left", "60")

    assert result.exit_code == 2
    assert "--time-left" in result.output


@pytest.mark.parametrize("seconds", ["nan", "inf", "-inf", "NaN", "infinity"])
def test_time_left_that_is_not_finite_is_refused(tmp_path: Path, seconds: str) -> None:
    """Given --time-left that is not a finite number of seconds, When `adhere
    --stage ci judge` runs, Then the command line is refused: no deadline
    can be computed from it."""
    result = adhere(tmp_path, "--stage", "ci", *JUDGE, "--time-left", seconds)

    assert result.exit_code == 2, result.output
    assert "--time-left" in result.output
