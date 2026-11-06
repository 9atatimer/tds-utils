"""The stage a run is bound for, chosen from one flag (ARCHITECTURE.ARCH-
ADHERENCE.md, Module map: cli/main.py; Mechanism > Where it runs): `adhere
--stage laptop|hook|ci|cloud`, the laptop by default; `judge --staged` is
the hook's entry (the pre-commit stage calls `bin/adhere judge --staged`),
so it binds the hook, and the hook judges nothing but the staged index."""

from __future__ import annotations

import functools
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeReportStore
from adherence.cli.main import main
from adherence.container import Stage
from tests.cli_kit import JUDGE, RecordingBuilder, adhere, faked


def test_help_lists_the_four_stages() -> None:
    """Given the adhere CLI, When `adhere --help` runs, Then its --stage
    option lists laptop, hook, ci and cloud."""
    result = CliRunner().invoke(main, ["--help"])

    (line,) = [
        ln for ln in result.output.splitlines() if ln.lstrip().startswith("--stage ")
    ]
    assert "[laptop|hook|ci|cloud]" in line


def test_stage_flag_binds_the_named_stage(tmp_path: Path) -> None:
    """Given `--stage ci` before judge and `--stage cloud` before measure,
    When each runs, Then the composition root is bound for that stage."""
    judged, measured = RecordingBuilder(faked()), RecordingBuilder(faked())

    adhere(tmp_path, "--stage", "ci", *JUDGE, builder=judged)
    adhere(tmp_path, "--stage", "cloud", "measure", builder=measured)

    assert (judged.stages, measured.stages) == ([Stage.CI], [Stage.CLOUD])


def test_no_stage_binds_the_laptop_and_staged_binds_the_hook(tmp_path: Path) -> None:
    """Given no --stage, When `adhere judge --base --head` runs, Then the
    laptop is bound; When `adhere judge --staged` runs, Then the hook is."""
    revisions, staged = RecordingBuilder(faked()), RecordingBuilder(faked())

    adhere(tmp_path, *JUDGE, builder=revisions)
    adhere(tmp_path, "judge", "--staged", builder=staged)

    assert (revisions.stages, staged.stages) == ([Stage.LAPTOP], [Stage.HOOK])


def test_staged_outside_the_hook_and_the_hook_on_revisions_are_refused(
    tmp_path: Path,
) -> None:
    """Given `--stage ci` with `judge --staged`, or `--stage hook` with
    `judge --base --head`, When either runs, Then the command line is
    refused before any port is bound."""
    builder = RecordingBuilder(faked())

    staged_in_ci = adhere(
        tmp_path, "--stage", "ci", "judge", "--staged", builder=builder
    )
    hook_on_revisions = adhere(tmp_path, "--stage", "hook", *JUDGE, builder=builder)

    assert (staged_in_ci.exit_code, hook_on_revisions.exit_code) == (2, 2)
    assert "--staged" in staged_in_ci.output and "hook" in hook_on_revisions.output
    assert builder.stages == []


def test_judge_names_the_change_as_the_stage_names_the_repository(
    tmp_path: Path,
) -> None:
    """Given GITHUB_REPOSITORY in the environment, When `adhere --stage ci
    judge` runs, Then the report kept names the repository `owner/repo`;
    When the laptop judges the same checkout, Then it names the checkout's
    directory."""
    environment = {"GITHUB_REPOSITORY": "someone/example"}
    in_ci, on_laptop = FakeReportStore(), FakeReportStore()

    adhere(
        tmp_path,
        "--stage",
        "ci",
        *JUDGE,
        builder=functools.partial(faked(), reports=in_ci, environment=environment),
    )
    adhere(
        tmp_path,
        *JUDGE,
        builder=functools.partial(faked(), reports=on_laptop, environment=environment),
    )

    assert [r.repository for r in in_ci.scanned] == ["someone/example"]
    assert [r.repository for r in on_laptop.scanned] == [tmp_path.name]
