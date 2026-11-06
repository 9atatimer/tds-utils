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
from collections.abc import Callable
from pathlib import Path

import click

from adherence.application.bounded import judge_bounded
from adherence.application.judge import judge_change
from adherence.application.load import load_declaration
from adherence.application.measure import measure
from adherence.application.record import record_report
from adherence.cli.presenters.json_report import report_json
from adherence.cli.presenters.plain import without_controls
from adherence.cli.presenters.summary import report_summary
from adherence.container import Container, Stage, build
from adherence.domain.deadline import Deadline
from adherence.domain.declaration import (
    DECLARATION_PATH,
    VOCABULARY_REFUSAL,
    Declaration,
    DeclarationUnreadable,
    RefusedExemption,
)
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Base, Change, Head

# --- Constants ---------------------------------------------------------------

# The verdicts `adhere judge` exits non-zero on until the per-stage mapping
# lands (task-066): lowered fails a gate; not run never reads as a pass.
# Inconclusive exits zero, so in the hook the commit proceeds.
FAILING = frozenset({Verdict.LOWERED, Verdict.NOT_RUN})
# The output formats: the machine form, and the PR job summary's markdown.
# The terminal and SARIF presenters are task-066's.
FORMATS = {"json": report_json, "summary": report_summary}
FORMAT_OPTION = click.option(
    "--format",
    "format_name",
    type=click.Choice(sorted(FORMATS)),
    default=None,
    help="The output format. Required until the terminal presenter lands.",
)
JSON_OPTION = click.option(
    "--json", "as_json", is_flag=True, help="Print the report as JSON (--format json)."
)

# --- Presenters --------------------------------------------------------------


def _safe(text: str) -> str:
    """Author-controlled text as the terminal may show it."""
    return without_controls(text)


def _refusal_line(refusal: RefusedExemption) -> str:
    exemption = refusal.exemption
    target = exemption.finding or f"{exemption.check} on {exemption.unit}"
    return _safe(f"  refused exemption: {target}: {refusal.reason}")


def _declaration_lines(loaded: Declaration | DeclarationUnreadable) -> list[str]:
    if isinstance(loaded, DeclarationUnreadable):
        return [_safe(f"declaration unreadable: {loaded.reason}")]
    if not loaded.declared:
        return [f"{DECLARATION_PATH}: none; the repository is measured as undeclared"]
    count = len(loaded.exemptions)
    return [
        f"{DECLARATION_PATH}: readable, {count} exemption{'s' if count != 1 else ''}",
        *map(_refusal_line, loaded.refused_exemptions),
        *(
            _safe(f"  refused vocabulary: {key}: {VOCABULARY_REFUSAL}")
            for key in loaded.vocabulary.refused
        ),
    ]


def _presenter(format_name: str | None, as_json: bool) -> Callable[..., str]:
    """The presenter the flags name; a usage error when they name none, or
    two: `--json` is `--format json`, so beside another format it is a
    conflict, never a silent loser."""
    if as_json and format_name not in (None, "json"):
        raise click.UsageError(
            f"--json is --format json; it conflicts with --format {format_name}"
        )
    if format_name is None and as_json:
        format_name = "json"
    if format_name is None:
        raise click.UsageError("name an output format: --format json or summary")
    return FORMATS[format_name]


# --- Entry points ------------------------------------------------------------


@click.group()
def main() -> None:
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
def declaration_check(root: str) -> None:
    """Read the working tree's adherence.toml and say whether it can be read."""
    container = build(Stage.LAPTOP, root=root)
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
    ctx: click.Context, root: str, format_name: str | None, as_json: bool
) -> None:
    """Measure the working tree and print the report.

    A test passes the composition root, bound with its fakes, as the
    context object.
    """
    present = _presenter(format_name, as_json)
    builder: Callable[..., Container] = ctx.obj if callable(ctx.obj) else build
    container = builder(Stage.LAPTOP, root=root)
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
    click.echo(present(report).rstrip("\n"))
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
        base=Base(container.staged_base),
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
    help="Judge the staged index against HEAD -- git's empty tree before the "
    "first commit -- within the commit-time bound (the pre-commit hook).",
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
    format_name: str | None,
    as_json: bool,
) -> None:
    """Judge the head revision against the base, or the staged index
    against HEAD (git's empty tree before the first commit), and print the
    report.

    The report is kept after the verdict is reached, so keeping it can
    never change the verdict. A test passes the composition root, bound
    with its fakes, as the context object.
    """
    present = _presenter(format_name, as_json)
    if staged == (base is not None or head is not None) or (
        not staged and (base is None or head is None)
    ):
        raise click.UsageError("give --base and --head, or --staged alone")
    builder: Callable[..., Container] = ctx.obj if callable(ctx.obj) else build
    if base is not None and head is not None:
        container = builder(Stage.LAPTOP, root=root)
        report = _judge_revisions(container, root, base, head)
    else:
        container = builder(Stage.HOOK, root=root)
        report = _judge_staged(container, root)
    recorded = record_report(report, reports=container.reports)
    click.echo(present(report, recorded).rstrip("\n"))
    if report.verdict in FAILING:
        sys.exit(1)
