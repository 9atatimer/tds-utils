"""orgmarks command-line entry point.

``plan`` is read-only and prints the report. ``apply`` writes the organized
Netscape HTML and appends learned rules to taxonomy.yml. Exit codes: 2 for
unparseable input or an invalid taxonomy; 0 otherwise (an unreachable LLM
degrades to rules-only rather than failing).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import click
from pydantic import ValidationError

from orgmarks.adapters.netscape import emit_netscape, parse_netscape
from orgmarks.adapters.taxonomy_yaml import load_taxonomy, write_learned_rules
from orgmarks.app.pipeline import Mode, PipelineResult, run
from orgmarks.domain.model import BookmarkTree
from orgmarks.domain.taxonomy import Taxonomy
from orgmarks.ports.classifier import Classifier

_INPUT_HELP = "Netscape HTML export (chrome://bookmarks -> Export)."
_PROFILE_HELP = "Path to a Chrome 'Bookmarks' JSON file (read-only)."


def _load_taxonomy_or_exit(path: Path) -> Taxonomy:
    try:
        return load_taxonomy(path)
    except ValidationError as err:
        click.echo(f"orgmarks: invalid taxonomy {path}:\n{err}", err=True)
        raise SystemExit(2) from err


def _load_tree_or_exit(
    input_file: Path | None, from_profile: Path | None
) -> BookmarkTree:
    try:
        if input_file is not None:
            return parse_netscape(input_file.read_text(encoding="utf-8"))
        assert from_profile is not None
        from orgmarks.adapters.chrome_json import parse_chrome_json

        return parse_chrome_json(from_profile.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError) as err:
        click.echo(f"orgmarks: cannot parse input: {err}", err=True)
        raise SystemExit(2) from err


def _make_classifier(taxonomy: Taxonomy) -> Classifier | None:
    """Build the classifier named by the taxonomy, or None for rules-only."""
    if taxonomy.llm is None:
        return None
    if taxonomy.llm.provider == "claude-cli":
        from orgmarks.adapters.claude_cli import ClaudeCliClassifier

        return ClaudeCliClassifier(model=taxonomy.llm.model)
    return None


def _resolve_date(raw: str | None) -> str:
    """Return a validated ISO date (YYYY-MM-DD) for the output filename.

    The value is normalized through ``date.fromisoformat`` so it can never
    smuggle path separators or ``..`` into the generated filename.
    """
    if raw:
        try:
            return datetime.date.fromisoformat(raw).isoformat()
        except ValueError as err:
            raise click.BadParameter(
                "must be an ISO date (YYYY-MM-DD)", param_hint="'--date'"
            ) from err
    return datetime.date.today().isoformat()


def _execute(
    *,
    mode: Mode,
    input_file: Path | None,
    from_profile: Path | None,
    taxonomy_path: Path,
    restructure: bool,
) -> PipelineResult:
    taxonomy = _load_taxonomy_or_exit(taxonomy_path)
    tree = _load_tree_or_exit(input_file, from_profile)
    classifier = _make_classifier(taxonomy)
    return run(tree, taxonomy, classifier, mode=mode, restructure=restructure)


_input_option = click.option(
    "--input",
    "input_file",
    type=click.Path(exists=True, path_type=Path),
    help=_INPUT_HELP,
)
_profile_option = click.option(
    "--from-profile",
    "from_profile",
    type=click.Path(exists=True, path_type=Path),
    help=_PROFILE_HELP,
)
_taxonomy_option = click.option(
    "--taxonomy",
    "taxonomy_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to taxonomy.yml.",
)
_restructure_option = click.option(
    "--restructure",
    is_flag=True,
    help=(
        "Re-file bookmarks already sitting in a valid intent path instead of "
        "leaving them put (disables the stay-put churn minimizer)."
    ),
)


def _require_one_source(input_file: Path | None, from_profile: Path | None) -> None:
    if (input_file is None) == (from_profile is None):
        raise click.UsageError("provide exactly one of --input or --from-profile")


@click.group()
def cli() -> None:
    """Groom a Chrome bookmark export around task intent."""


@cli.command()
@_input_option
@_profile_option
@_taxonomy_option
@_restructure_option
def plan(
    input_file: Path | None,
    from_profile: Path | None,
    taxonomy_path: Path,
    restructure: bool,
) -> None:
    """Print the move/create/merge report (read-only)."""
    _require_one_source(input_file, from_profile)
    result = _execute(
        mode="plan",
        input_file=input_file,
        from_profile=from_profile,
        taxonomy_path=taxonomy_path,
        restructure=restructure,
    )
    click.echo(result.report)


@cli.command()
@_input_option
@_profile_option
@_taxonomy_option
@_restructure_option
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    help="Where to write the organized HTML.",
)
@click.option("--date", "date_str", hidden=True, default=None)
def apply(
    input_file: Path | None,
    from_profile: Path | None,
    taxonomy_path: Path,
    restructure: bool,
    output_dir: Path,
    date_str: str | None,
) -> None:
    """Write the organized HTML and append learned rules to taxonomy.yml."""
    _require_one_source(input_file, from_profile)
    result = _execute(
        mode="apply",
        input_file=input_file,
        from_profile=from_profile,
        taxonomy_path=taxonomy_path,
        restructure=restructure,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"bookmarks-organized-{_resolve_date(date_str)}.html"
    out_path.write_text(emit_netscape(result.organized), encoding="utf-8")
    write_learned_rules(taxonomy_path, result.plan.learned_rules)
    click.echo(result.report)
    click.echo("")
    click.echo(f"wrote {out_path}")


def main() -> None:
    """Console entry point."""
    cli()


if __name__ == "__main__":
    main()
