"""cli/main.py -- the adhere CLI: parse, call the use cases, present.

Holds no workflow step and constructs no adapter: container.build binds
the ports (ARCHITECTURE.ARCH-ADHERENCE.md, Module map). Declaration text
is author-controlled, so control characters are stripped before it
reaches the terminal (Security mitigations).
"""

from __future__ import annotations

import sys
import unicodedata

import click

from adherence.application.load import load_declaration
from adherence.container import Stage, build
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    DeclarationUnreadable,
    RefusedExemption,
)
from adherence.domain.target import Head

# --- Constants ---------------------------------------------------------------

# Unicode control (newline and tab included) and format (bidi overrides,
# zero-width) characters: none of them may reach the terminal.
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})

# --- Presenters --------------------------------------------------------------


def _safe(text: str) -> str:
    """Author-controlled text with every control and format character removed,
    so it can neither start a line nor reorder one."""
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in STRIPPED_CATEGORIES
    )


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
    ]


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
