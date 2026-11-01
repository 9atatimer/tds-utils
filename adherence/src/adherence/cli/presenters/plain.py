"""cli/presenters/plain.py -- author-controlled text made safe for a surface.

Evidence, symbols, paths and declaration text come from the code under
measurement, so every presenter strips what could start a line, reorder
one or hide in it before the text reaches a terminal or a page
(ARCHITECTURE.ARCH-ADHERENCE.md, Security mitigations). One rule, one
place: the terminal and the job summary strip the same characters.
"""

from __future__ import annotations

import re
import unicodedata

# Unicode control (newline and tab included) and format (bidi overrides,
# zero-width) characters: none of them may reach any surface.
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})
# A lone surrogate, as surrogateescape decodes a byte that is not UTF-8:
# no encoder writes it, so it is shown as the replacement character.
SURROGATE = "Cs"
REPLACEMENT = "\ufffd"
# An escape sequence whole, parameters included, so stripping its ESC never
# leaves them behind as text: CSI (7- and 8-bit), OSC and the string
# controls up to their terminator, and the two-byte escapes.
ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r"|\x1b[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[ -/]*[0-~]"
)


def without_controls(text: str) -> str:
    """The text with every ANSI escape sequence, control and format
    character removed, so it can neither recolour a terminal, start a line
    nor reorder one, and every lone surrogate replaced, so every stream can
    write it."""
    return "".join(
        REPLACEMENT if unicodedata.category(ch) == SURROGATE else ch
        for ch in ANSI_ESCAPE.sub("", text)
        if unicodedata.category(ch) not in STRIPPED_CATEGORIES
    )
