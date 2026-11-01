"""cli/main.py -- the adhere CLI: parse, call the use cases, present.

Holds no workflow step and constructs no adapter: container.build binds
the ports (ARCHITECTURE.ARCH-ADHERENCE.md, Module map). It computes the
hook's Deadline from the commit-time bound, the one place the engine turns
a bound into an instant, and in the hook calls judge_bounded instead of
judge_change. Declaration text
is author-controlled, so control characters are stripped before it
reaches the terminal (Security mitigations).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import click

from adherence.application.bounded import judge_bounded
from adherence.application.judge import judge_change
from adherence.application.load import load_declaration
from adherence.application.measure import measure
from adherence.application.record import record_report
from adherence.cli.presenters.json_report import report_json
from adherence.cli.presenters.sarif import report_sarif
from adherence.cli.presenters.summary import report_summary
from adherence.cli.presenters.terminal import report_text, safe_text
from adherence.container import Container, Stage, build
from adherence.domain.deadline import Deadline
from adherence.domain.declaration import (
    DECLARATION_PATH,
    VOCABULARY_REFUSAL,
    Declaration,
    DeclarationUnreadable,
    RefusedExemption,
)
from adherence.domain.report import Recorded, Report, Verdict
from adherence.domain.target import Base, Change, Head

# --- Constants ---------------------------------------------------------------

# The verdicts `adhere judge` exits non-zero on, per stage. Lowered fails a
# gate, and not run never reads as a pass, in every stage. Inconclusive
# exits zero in the hook, so the commit proceeds (The hook), and on the
# laptop and in the cloud, where an agent reads the report; at the gate it
# never reads as a pass. Whether the gate may let inconclusive and not run
# merge is the design's Q10: until it is ruled, ci fails closed.
FAILING: Mapping[Stage, frozenset[Verdict]] = {
    Stage.LAPTOP: frozenset({Verdict.LOWERED, Verdict.NOT_RUN}),
    Stage.HOOK: frozenset({Verdict.LOWERED, Verdict.NOT_RUN}),
    Stage.CI: frozenset({Verdict.LOWERED, Verdict.NOT_RUN, Verdict.INCONCLUSIVE}),
    Stage.CLOUD: frozenset({Verdict.LOWERED, Verdict.NOT_RUN}),
}
# The hook judges what is staged against the commit it will follow.
HOOK_BASE = "HEAD"
# Each surface a report is printed for, by the name `--format` takes.
PRESENTERS: dict[str, Callable[[Report, Recorded | None], str]] = {
    "terminal": report_text,
    "json": report_json,
    "sarif": report_sarif,
    "summary": report_summary,
}

# --- Presenters --------------------------------------------------------------


def _refusal_line(refusal: RefusedExemption) -> str:
    exemption = refusal.exemption
    target = exemption.finding or f"{exemption.check} on {exemption.unit}"
    return safe_text(f"  refused exemption: {target}: {refusal.reason}")


def _declaration_lines(loaded: Declaration | DeclarationUnreadable) -> list[str]:
    if isinstance(loaded, DeclarationUnreadable):
        return [safe_text(f"declaration unreadable: {loaded.reason}")]
    if not loaded.declared:
        return [f"{DECLARATION_PATH}: none; the repository is measured as undeclared"]
    count = len(loaded.exemptions)
    return [
        f"{DECLARATION_PATH}: readable, {count} exemption{'s' if count != 1 else ''}",
        *map(_refusal_line, loaded.refused_exemptions),
        *(
            safe_text(f"  refused vocabulary: {key}: {VOCABULARY_REFUSAL}")
            for key in loaded.vocabulary.refused
        ),
    ]


def _presenter(
    output_format: str | None, as_json: bool
) -> Callable[[Report, Recorded | None], str]:
    """The presenter `--format` names, `--json` naming JSON; the terminal's
    when neither is given."""
    if as_json and output_format not in (None, "json"):
        raise click.UsageError("give --json or --format, not both")
    return PRESENTERS["json" if as_json else output_format or "terminal"]


# --- Entry points ------------------------------------------------------------

FORMAT_OPTION = click.option(
    "--format",
    "output_format",
    type=click.Choice(list(PRESENTERS)),
    help="How the report is printed: terminal lines (the default), JSON, "
    "SARIF 2.1.0, or the PR job summary in markdown.",
)
JSON_OPTION = click.option(
    "--json", "as_json", is_flag=True, help="Print the report as JSON (--format json)."
)


def _chosen_stage(ctx: click.Context) -> Stage | None:
    """The stage `--stage` named on the command line, if it named one."""
    name = ctx.find_root().params.get("stage")
    return Stage(name) if isinstance(name, str) else None


def _judging_stage(ctx: click.Context, staged: bool) -> Stage:
    """The stage a judgement runs in: the one named, else the hook for the
    staged index and the laptop for revisions. Only the hook judges the
    staged index, and the hook judges nothing else."""
    stage = _chosen_stage(ctx) or (Stage.HOOK if staged else Stage.LAPTOP)
    if staged and stage is not Stage.HOOK:
        raise click.UsageError(f"--staged is the hook's; not the {stage.value} stage")
    if not staged and stage is Stage.HOOK:
        raise click.UsageError("the hook stage judges the staged index: give --staged")
    return stage


@click.group()
@click.option(
    "--stage",
    type=click.Choice([stage.value for stage in Stage]),
    help="The place this run is in, which binds its judge, reviews and "
    "bound: laptop (the default), hook (judge --staged), ci (the gate) or "
    "cloud.",
)
def main(stage: str | None) -> None:
    """adhere -- measure a repository against its own declared architecture."""


@main.group()
def declaration() -> None:
    """The repository's adherence.toml."""


@declaration.command("check")
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False),
    help="The repository whose working tree is read.",
)
@click.pass_context
def declaration_check(ctx: click.Context, root: str) -> None:
    """Read the working tree's adherence.toml and say whether it can be read."""
    container = build(_chosen_stage(ctx) or Stage.LAPTOP, root=root)
    loaded = load_declaration(
        Head.working_tree(), repository=container.repository, deadline=None
    )
    for line in _declaration_lines(loaded):
        click.echo(line)
    if isinstance(loaded, DeclarationUnreadable):
        sys.exit(1)


@main.command("measure")
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False),
    help="The repository whose working tree is measured.",
)
@FORMAT_OPTION
@JSON_OPTION
@click.pass_context
def measure_command(
    ctx: click.Context, root: str, output_format: str | None, as_json: bool
) -> None:
    """Measure the working tree and print the report.

    A test passes the composition root, bound with its fakes, as the
    context object.
    """
    present = _presenter(output_format, as_json)
    builder: Callable[..., Container] = ctx.obj if callable(ctx.obj) else build
    container = builder(_chosen_stage(ctx) or Stage.LAPTOP, root=root)
    head = Head.working_tree()
    report = measure(
        head,
        load_declaration(head, repository=container.repository, deadline=None),
        repository=container.repository,
        analyzers=container.analyzers,
        complexity=container.complexity,
        duplication=container.duplication,
        records=container.records,
        judge=container.judge,
        parameters=container.parameters,
        deadline=None,
    )
    click.echo(present(report, None))
    if report.not_run_reason is not None:
        sys.exit(1)


def _judge_revisions(container: Container, root: str, base: str, head: str) -> Report:
    change = Change(
        repository=Path(root).resolve().name,
        base=Base(base),
        head=Head.at_revision(head),
    )
    return judge_change(
        change,
        repository=container.repository,
        reviews=container.reviews,
        analyzers=container.analyzers,
        complexity=container.complexity,
        duplication=container.duplication,
        records=container.records,
        judge=container.judge,
        reports=container.reports,
        parameters=container.parameters,
        deadline=None,
    )


def _judge_staged(container: Container, root: str) -> Report:
    bound = container.parameters.limits.commit_time_bound
    if container.worker is None or bound is None:
        raise click.UsageError("the hook stage binds no worker or no time bound")
    change = Change(
        repository=Path(root).resolve().name,
        base=Base(HOOK_BASE),
        head=Head.staged_index(),
    )
    return judge_bounded(
        change,
        worker=container.worker,
        deadline=Deadline(epoch_seconds=time.time() + bound),
        repository=container.repository,
        reviews=container.reviews,
        analyzers=container.analyzers,
        complexity=container.complexity,
        duplication=container.duplication,
        records=container.records,
        judge=container.judge,
        reports=container.reports,
        parameters=container.parameters,
    )


@main.command("judge")
@click.option(
    "--root",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False),
    help="The repository whose revisions are judged.",
)
@click.option("--base", help="The revision judged against.")
@click.option("--head", help="The revision judged.")
@click.option(
    "--staged",
    is_flag=True,
    help="Judge the staged index against HEAD within the commit-time bound "
    "(the pre-commit hook).",
)
@FORMAT_OPTION
@JSON_OPTION
@click.pass_context
def judge_command(
    ctx: click.Context,
    root: str,
    base: str | None,
    head: str | None,
    staged: bool,
    output_format: str | None,
    as_json: bool,
) -> None:
    """Judge the head revision against the base, or the staged index
    against HEAD, and print the report.

    The report is kept after the verdict is reached, so keeping it can
    never change the verdict. A test passes the composition root, bound
    with its fakes, as the context object.
    """
    present = _presenter(output_format, as_json)
    if staged == (base is not None or head is not None) or (
        not staged and (base is None or head is None)
    ):
        raise click.UsageError("give --base and --head, or --staged alone")
    stage = _judging_stage(ctx, staged)
    builder: Callable[..., Container] = ctx.obj if callable(ctx.obj) else build
    container = builder(stage, root=root)
    if base is not None and head is not None:
        report = _judge_revisions(container, root, base, head)
    else:
        report = _judge_staged(container, root)
    recorded = record_report(report, reports=container.reports)
    click.echo(present(report, recorded))
    if report.verdict in FAILING[stage]:
        sys.exit(1)
