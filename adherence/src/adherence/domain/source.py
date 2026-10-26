"""domain/source.py -- source text as a language's parser counts its lines.

Only `\\r\\n`, `\\r` and `\\n` end a line for Python's parser;
str.splitlines() also breaks on form feed and other characters, which
would shift every line number after one (ARCHITECTURE.ARCH-ADHERENCE.md,
Findings and explanations: evidence is located by line).
"""

from __future__ import annotations

import re

# --- Constants ---------------------------------------------------------------

LINE_BREAK = re.compile(r"\r\n|\r|\n")

# --- Pure helpers ------------------------------------------------------------


def source_lines(text: str) -> list[str]:
    """The text's lines, numbered from 1 as the parser numbers them; a final
    line break ends the last line rather than opening an empty one."""
    lines = LINE_BREAK.split(text)
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines
