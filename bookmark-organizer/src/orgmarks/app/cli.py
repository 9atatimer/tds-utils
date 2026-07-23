"""orgmarks command-line entry point.

Phase 0 stub: the ``plan`` and ``apply`` commands are wired to real pipeline
logic in the app phase. For now they parse flags and echo their mode so the
launcher shim and ``--help`` work end to end.
"""

from __future__ import annotations

import click


@click.group()
def cli() -> None:
    """Groom a Chrome bookmark export around task intent."""


@cli.command()
def plan() -> None:
    """Print the move/create/merge report (read-only). Stub."""
    click.echo("orgmarks plan: not yet implemented")


@cli.command()
def apply() -> None:
    """Write the organized HTML and learned rules. Stub."""
    click.echo("orgmarks apply: not yet implemented")


def main() -> None:
    """Console entry point."""
    cli()


if __name__ == "__main__":
    main()
