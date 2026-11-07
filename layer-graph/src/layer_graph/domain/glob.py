"""Layer glob matching, with the adherence engine's semantics.

`**` as a whole segment crosses directories (zero or more segments before a
further segment, one or more at the end); `*`, `?` and `[...]` stay within
one segment (tds-utils adherence/src/adherence/domain/declaration.py,
`matches`).
"""

import fnmatch

# --- Constants ---------------------------------------------------------------

GLOB_CHARACTERS = frozenset("*?[")

# --- Predicates --------------------------------------------------------------


def is_literal(pattern: str) -> bool:
    """Whether a pattern names one path rather than a glob."""
    return not GLOB_CHARACTERS & set(pattern)


def matches(pattern: str, path: str) -> bool:
    """Whether a repository path matches a layer pattern.

    Matched segment by segment over a table, never by a backtracking regex,
    so the cost stays linear in the pattern times the path.
    """
    parts = pattern.split("/")
    segments = path.split("/")
    tail = [False] * len(segments) + [True]
    for i in range(len(parts) - 1, -1, -1):
        row = [False] * (len(segments) + 1)
        for j in range(len(segments), -1, -1):
            if parts[i] == "**":
                at_end = i == len(parts) - 1
                row[j] = (
                    j < len(segments) and (row[j + 1] or (at_end and tail[j + 1]))
                ) or (not at_end and tail[j])
            else:
                row[j] = (
                    j < len(segments)
                    and fnmatch.fnmatchcase(segments[j], parts[i])
                    and tail[j + 1]
                )
        tail = row
    return tail[0]


# --- Pure helpers ------------------------------------------------------------


def static_prefix(pattern: str) -> str:
    """The segments of a pattern before its first wildcard segment; the whole
    pattern when it is literal."""
    kept: list[str] = []
    for segment in pattern.split("/"):
        if GLOB_CHARACTERS & set(segment):
            break
        kept.append(segment)
    return "/".join(kept)


def specificity(pattern: str) -> tuple[bool, int]:
    """How strongly a pattern claims a path it matches: a literal beats a
    glob, then a longer pattern beats a shorter one (the engine's rule)."""
    return (is_literal(pattern), len(pattern))
