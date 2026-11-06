"""cli/presenters/plain.py -- author-controlled text made safe for a surface.

Evidence, symbols, paths and declaration text come from the code under
measurement, so every presenter strips what could start a line, reorder
one or hide in it before the text reaches a terminal or a page
(ARCHITECTURE.ARCH-ADHERENCE.md, Security mitigations). One rule, one
place: the terminal and the job summary strip the same characters.
"""

from __future__ import annotations

import unicodedata

# Unicode control (newline and tab included) and format (bidi overrides,
# zero-width) characters: none of them may reach any surface.
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})


def without_controls(text: str) -> str:
    """The text with every control and format character removed, so it can
    neither start a line nor reorder one."""
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in STRIPPED_CATEGORIES
    )
