"""domain/declaration.py -- a repository's Declaration, parsed and validated.

The one owner of what a declaration says (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map). Values in, values out: the bytes arrive from RepositoryPort
through the use case. adherence.toml is TOML read with the standard
library; its tables are the architecture's (Mechanism, Measurement).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from adherence.domain.model import Layer, Region
from adherence.domain.parameters import Vocabulary
from adherence.domain.qualities import Quality, check_named

# --- Constants ---------------------------------------------------------------

DECLARATION_PATH = "adherence.toml"

TABLES = frozenset(
    {"layers", "runtimes", "records", "radar", "exemptions", "limits", "vocabulary"}
)
EXEMPTION_KEYS = frozenset({"check", "unit", "finding", "reason"})
DECLARED_REFUSAL = "the Declared quality's checks cannot be exempted"
REGIONS_KEY = "regions"
LAYER_NAMES = {layer.value: layer for layer in Layer}
GLOB_CHARACTERS = frozenset("*?[")
# `# --- Action functions ---`, with any run of trailing dashes.
SECTION_MARKER = re.compile(r"^\s*#\s*---\s*(?P<name>[^-].*?)\s*-*\s*$")

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Exemption:
    """An owner's statement that a unit is not checked by one check, or that
    one finding is dismissed, with a reason."""

    reason: str
    check: str | None = None
    unit: str | None = None
    finding: str | None = None


@dataclass(frozen=True, slots=True)
class RefusedExemption:
    """An exemption the declaration states and the suite will not honor."""

    exemption: Exemption
    reason: str


@dataclass(frozen=True, slots=True)
class Layers:
    """The [layers] table: globs and literal paths per layer, line-range
    regions, and the files whose regions come from their section markers."""

    globs: tuple[tuple[Layer, str], ...] = ()
    regions: tuple[Region, ...] = ()
    marker_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Declaration:
    """A repository's statement of its layers, runtimes, records, radar and
    exemptions. Declaration.none is the value for a repository that has none.
    """

    declared: bool = True
    layers: Layers = field(default_factory=Layers)
    exemptions: tuple[Exemption, ...] = ()
    refused_exemptions: tuple[RefusedExemption, ...] = ()

    none: ClassVar[Declaration]


Declaration.none = Declaration(declared=False)


@dataclass(frozen=True, slots=True)
class DeclarationUnreadable:
    """The outcome of a declaration that cannot be read, with the reason."""

    reason: str


# --- Predicates --------------------------------------------------------------


def is_literal(pattern: str) -> bool:
    """Whether a layer pattern names one path rather than a glob."""
    return not GLOB_CHARACTERS & set(pattern)


def matches(pattern: str, path: str) -> bool:
    """Whether a repository path matches a layer pattern: `**` crosses
    directories, `*` and `?` stay within one."""
    return re.fullmatch(_glob_regex(pattern), path) is not None


def is_declared_check(name: str | None) -> bool:
    """Whether the check named is one of the Declared quality's."""
    check = check_named(name) if name else None
    return check is not None and check.quality is Quality.DECLARED


# --- Pure helpers ------------------------------------------------------------


def _glob_regex(pattern: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return "".join(out)


def marker_regions(path: str, text: str, vocabulary: Vocabulary) -> tuple[Region, ...]:
    """The regions a file's section markers open: from each marker the
    vocabulary knows to the line before the next marker, or the end of the
    file. A marker it does not know closes the region before it."""
    lines = text.splitlines()
    markers = [
        (number, match.group("name").lower())
        for number, line in enumerate(lines, start=1)
        if (match := SECTION_MARKER.match(line))
    ]
    regions: list[Region] = []
    for index, (start, name) in enumerate(markers):
        layer = vocabulary.regions.get(name)
        if layer is None:
            continue
        end = markers[index + 1][0] - 1 if index + 1 < len(markers) else len(lines)
        regions.append(Region(path, start, end, layer))
    return tuple(regions)


def layer_of(
    path: str,
    line: int | None,
    declaration: Declaration,
    found: Sequence[Region] = (),
) -> Layer | None:
    """The one layer a file, or a line of it, is in; None when uncovered.

    A region (declared by lines, or found by marker and passed in) beats a
    file; a literal path beats a glob; a longer glob beats a shorter one.
    """
    if line is not None:
        for region in (*declaration.layers.regions, *found):
            if region.holds(path, line):
                return region.layer
    hits = [
        (is_literal(pattern), len(pattern), layer)
        for layer, pattern in declaration.layers.globs
        if matches(pattern, path)
    ]
    if not hits:
        return None
    return max(hits, key=lambda hit: (hit[0], hit[1]))[2]


def _region(entry: object, number: int) -> Region | str | DeclarationUnreadable:
    """One regions entry: a Region by lines, the path of a marker file, or
    why it cannot be read."""
    where = f"{DECLARATION_PATH}: layers region {number}"
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return DeclarationUnreadable(f"{where} names no file")
    unknown = sorted(set(entry) - {"file", "layer", "lines"})
    if unknown:
        return DeclarationUnreadable(
            f"{where} has unknown key(s): {', '.join(unknown)}"
        )
    if "layer" not in entry and "lines" not in entry:
        return str(entry["file"])
    layer = LAYER_NAMES.get(str(entry.get("layer")))
    if layer is None:
        return DeclarationUnreadable(f"{where} names no known layer")
    lines = entry.get("lines")
    if not (
        isinstance(lines, list)
        and len(lines) == 2
        and all(isinstance(n, int) and n >= 1 for n in lines)
        and lines[0] <= lines[1]
    ):
        return DeclarationUnreadable(
            f"{where} needs lines = [first, last], first <= last"
        )
    return Region(str(entry["file"]), lines[0], lines[1], layer)


def _layers(value: object) -> Layers | DeclarationUnreadable:
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{DECLARATION_PATH}: layers is a table")
    globs: list[tuple[Layer, str]] = []
    regions: list[Region] = []
    marker_files: list[str] = []
    for key, patterns in value.items():
        if key == REGIONS_KEY:
            if not isinstance(patterns, list):
                return DeclarationUnreadable(
                    f"{DECLARATION_PATH}: layers.regions is a list"
                )
            for number, entry in enumerate(patterns, start=1):
                region = _region(entry, number)
                if isinstance(region, DeclarationUnreadable):
                    return region
                if isinstance(region, Region):
                    regions.append(region)
                else:
                    marker_files.append(region)
            continue
        layer = LAYER_NAMES.get(key)
        if layer is None:
            return DeclarationUnreadable(f"{DECLARATION_PATH}: {key} is not a layer")
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) for p in patterns
        ):
            return DeclarationUnreadable(
                f"{DECLARATION_PATH}: layers.{key} is a list of path patterns"
            )
        globs.extend((layer, pattern) for pattern in patterns)
    return Layers(tuple(globs), tuple(regions), tuple(marker_files))


def _text_field(entry: Mapping[str, object], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) and value else None


def _exemption(entry: object, number: int) -> Exemption | DeclarationUnreadable:
    """One [[exemptions]] entry, or why it cannot be read."""
    where = f"{DECLARATION_PATH}: exemption {number}"
    if not isinstance(entry, dict):
        return DeclarationUnreadable(f"{where} is not a table")
    unknown = sorted(set(entry) - EXEMPTION_KEYS)
    if unknown:
        return DeclarationUnreadable(
            f"{where} has unknown key(s): {', '.join(unknown)}"
        )
    if any(not isinstance(entry[key], str) for key in entry):
        return DeclarationUnreadable(f"{where} has a value that is not a string")
    reason = _text_field(entry, "reason")
    if reason is None:
        return DeclarationUnreadable(f"{where} has no reason")
    check = _text_field(entry, "check")
    unit = _text_field(entry, "unit")
    finding = _text_field(entry, "finding")
    if finding is not None and (check or unit):
        return DeclarationUnreadable(
            f"{where} names a finding and a check or unit; it names one or the other"
        )
    if finding is None and not (check and unit):
        return DeclarationUnreadable(
            f"{where} names a unit and a check, or one finding; it has neither"
        )
    return Exemption(reason=reason, check=check, unit=unit, finding=finding)


def _exemptions(value: object) -> tuple[Exemption, ...] | DeclarationUnreadable:
    if not isinstance(value, list):
        return DeclarationUnreadable(
            f"{DECLARATION_PATH}: exemptions is an array of tables ([[exemptions]])"
        )
    parsed: list[Exemption] = []
    for number, entry in enumerate(value, start=1):
        exemption = _exemption(entry, number)
        if isinstance(exemption, DeclarationUnreadable):
            return exemption
        parsed.append(exemption)
    return tuple(parsed)


def parse_declaration(text: bytes) -> Declaration | DeclarationUnreadable:
    """The Declaration that adherence.toml's bytes state, or why they cannot
    be read."""
    try:
        document = tomllib.loads(text.decode("utf-8"))
    except UnicodeDecodeError as error:
        return DeclarationUnreadable(f"{DECLARATION_PATH} is not utf-8: {error}")
    except tomllib.TOMLDecodeError as error:
        return DeclarationUnreadable(f"{DECLARATION_PATH}: {error}")
    except ValueError as error:
        # tomllib's own conversions (an integer past Python's digit limit)
        # raise a plain ValueError rather than TOMLDecodeError.
        return DeclarationUnreadable(f"{DECLARATION_PATH}: {error}")
    except RecursionError:
        return DeclarationUnreadable(
            f"{DECLARATION_PATH} is nested deeper than the parser can follow"
        )
    unknown = sorted(set(document) - TABLES)
    if unknown:
        return DeclarationUnreadable(
            f"{DECLARATION_PATH}: unknown table(s): {', '.join(unknown)}"
        )
    layers = _layers(document.get("layers", {}))
    if isinstance(layers, DeclarationUnreadable):
        return layers
    exemptions = _exemptions(document.get("exemptions", []))
    if isinstance(exemptions, DeclarationUnreadable):
        return exemptions
    return Declaration(
        layers=layers,
        exemptions=tuple(e for e in exemptions if not is_declared_check(e.check)),
        refused_exemptions=tuple(
            RefusedExemption(e, DECLARED_REFUSAL)
            for e in exemptions
            if is_declared_check(e.check)
        ),
    )
