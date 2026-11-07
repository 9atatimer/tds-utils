"""Contexts: which node of its layer a unit file belongs to.

A node is (layer, context). The context is the first path segment after the
matching glob's static prefix when the file sits in a subdirectory of it;
otherwise a label taken from the prefix. Two origins in one layer that yield
one context name are told apart by their package directory, or failing that
by the first path segment where their prefixes differ.
"""

import posixpath
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from layer_graph.domain.glob import is_literal, static_prefix

# --- Constants ---------------------------------------------------------------

# Directory names that say nothing about the code in them: a prefix ending
# in one is labelled by the directory above it.
GENERIC_SEGMENTS = frozenset({"src", "lib", "source"})
ROOT_LABEL = "root"
QUALIFIER_SEPARATOR = ":"


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a context name came from: the layer, the glob's static prefix,
    the unqualified context, and the package directory holding the prefix."""

    layer: str
    prefix: str
    context: str
    package: str


# --- Pure helpers ------------------------------------------------------------


def prefix_label(prefix: str, *, literal: bool) -> str:
    """The label for files directly in a prefix: a single-file glob's stem,
    else the prefix's last segment that is not generic."""
    if literal:
        return posixpath.splitext(posixpath.basename(prefix))[0]
    segments = [s for s in prefix.split("/") if s]
    for segment in reversed(segments):
        if segment not in GENERIC_SEGMENTS:
            return segment
    return segments[-1] if segments else ROOT_LABEL


def context_for(pattern: str, path: str) -> str:
    """The unqualified context of a path under the pattern that claims it."""
    literal = is_literal(pattern)
    prefix = static_prefix(pattern)
    if not literal:
        below = path[len(prefix) + 1 :] if prefix else path
        segments = below.split("/")
        if len(segments) > 1:
            return segments[0]
    return prefix_label(prefix, literal=literal)


def package_of(prefix: str, package_dirs: Iterable[str]) -> str:
    """The deepest package directory holding a prefix; "" for none."""
    best = ""
    for directory in package_dirs:
        if directory and (prefix == directory or prefix.startswith(directory + "/")):
            if len(directory) > len(best):
                best = directory
    return best


def _differing_segments(prefixes: list[str]) -> list[str]:
    split = [p.split("/") for p in prefixes]
    width = min(len(s) for s in split)
    for index in range(width):
        if len({s[index] for s in split}) > 1:
            return [s[index] for s in split]
    return prefixes


def _qualifiers(origins: list[Origin]) -> list[str]:
    packages = [posixpath.basename(o.package) if o.package else "" for o in origins]
    if all(packages) and len(set(packages)) == len(packages):
        return packages
    differing = _differing_segments([o.prefix for o in origins])
    if len(set(differing)) == len(differing):
        return differing
    return [o.prefix for o in origins]


def qualified_contexts(origins: Iterable[Origin]) -> dict[Origin, str]:
    """Each origin's context name, qualified where another origin in the same
    layer yields the same name from a different prefix."""
    groups: dict[tuple[str, str], list[Origin]] = defaultdict(list)
    for origin in origins:
        group = groups[(origin.layer, origin.context)]
        if origin not in group:
            group.append(origin)
    named: dict[Origin, str] = {}
    for (_, context), group in groups.items():
        prefixes = sorted({o.prefix for o in group})
        if len(prefixes) == 1:
            named.update({o: context for o in group})
            continue
        by_prefix = {o.prefix: o for o in group}
        representatives = [by_prefix[p] for p in prefixes]
        for representative, qualifier in zip(
            representatives, _qualifiers(representatives), strict=True
        ):
            for origin in group:
                if origin.prefix == representative.prefix:
                    named[origin] = f"{qualifier}{QUALIFIER_SEPARATOR}{context}"
    return named
