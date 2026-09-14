"""Entry point for the ``chores`` command.

Thin by design (coding skill 1.7): parse arguments, call an application
function, shape the result. The composition root that wires adapters to
ports lives in :mod:`chores.cli.wiring` once the first use case exists.
"""

from __future__ import annotations

import click

from chores import __version__


@click.group()
@click.version_option(__version__, prog_name="chores")
def main() -> None:
    """Laptop-local herd of LLM-adjacent scheduled jobs."""
