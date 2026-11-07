"""domain/declaration.py -- a repository's Declaration, parsed and validated.

The one owner of what a declaration says (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map). Values in, values out: the bytes arrive from RepositoryPort
through the use case. adherence.toml is TOML read with the standard
library; its tables are the architecture's (Mechanism, Measurement).
"""

from __future__ import annotations

import dataclasses
import fnmatch
import itertools
import re
import tomllib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import ClassVar, TypeVar

from adherence.domain.finding import Finding, Notice
from adherence.domain.model import Layer, Region
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import Quality, check_named
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

# The name of a declaration file; any directory may hold one, and it
# governs that directory's subtree (DESIGN.ARCH-ADHERENCE.md, The
# declaration). The root's file is at this path.
DECLARATION_PATH = "adherence.toml"
OVERRIDE = "override"
# The sections one value of which governs a path: the nearest governing
# file's. Every other section is a union across the governing files.
SINGLE_VALUED = frozenset({"records", "radar", "limits"})
ESCAPES = "escapes its directory"

TABLES = frozenset(
    {"layers", "runtimes", "records", "radar", "exemptions", "limits", "vocabulary"}
)
EXEMPTION_KEYS = frozenset({"check", "unit", "finding", "reason"})
RECORD_KEYS = ("design", "architecture")
RADAR_KEY = "path"
DECLARED_REFUSAL = "the Declared quality's checks cannot be exempted"
REGIONS_KEY = "regions"
LAYER_NAMES = {layer.value: layer for layer in Layer}
GLOB_CHARACTERS = frozenset("*?[")
# `# --- Action functions ---` (shell, Python) or `// --- Action functions ---`
# (TypeScript, JavaScript), with any run of trailing dashes.
SECTION_MARKER = re.compile(r"^\s*(?:#|//)\s*---\s*(?P<name>[^-].*?)\s*-*\s*$")
# The [vocabulary] keys: every word set Vocabulary carries, and regions.
WORD_SETS = frozenset(
    f.name for f in dataclasses.fields(Vocabulary) if f.name != REGIONS_KEY
)
# The word sets a declaration may extend: those whose words only make more
# things count as a flaw. Every other set's words excuse (a fake prefix, a
# plain type), so extending it would weaken a check; it is refused.
FINDING_SETS = frozenset(
    {
        "environment_reads",
        "sleeps",
        "stubs",
        "vendors",
        "model_ids",
        "mechanism_calls",
        "clocks",
        "callables",
        "wire_formats",
        "singletons",
        "placeholder_assertions",
    }
)
VOCABULARY_REFUSAL = (
    "a declaration extends only the vocabularies whose words add findings; "
    "this one's words would excuse them"
)

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Exemption:
    """An owner's statement that a unit is not checked by one check, or that
    one finding is dismissed, with a reason."""

    reason: str
    check: str | None = None
    unit: str | None = None
    finding: str | None = None
    # The subtree of the file that states it, and the subtrees where a
    # nearer declaration's [override.exemptions] voids it.
    within: str = ""
    outside: tuple[str, ...] = ()

    def reaches(self, path: str) -> bool:
        """Whether the exemption applies at the path at all."""
        return is_under(path, self.within) and not any(
            is_under(path, d) for d in self.outside
        )


@dataclass(frozen=True, slots=True)
class RefusedExemption:
    """An exemption the declaration states and the suite will not honor."""

    exemption: Exemption
    reason: str


@dataclass(frozen=True, slots=True)
class Layers:
    """The [layers] table: globs and literal paths per layer, line-range
    regions, and the files whose regions come from their section markers;
    and the layer a change's widening gives each file it created, matched
    by that path alone, never as a glob."""

    globs: tuple[tuple[Layer, str], ...] = ()
    regions: tuple[Region, ...] = ()
    marker_files: tuple[str, ...] = ()
    widened: tuple[tuple[Layer, str], ...] = ()
    # (index into globs, subtree): the glob does not apply in the subtree,
    # where a nearer declaration's [override.layers] replaces the section.
    voided: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class VocabularyExtension:
    """The [vocabulary] table: the words added to each word set, the region
    markers added, each to the layer its region is in, and the word sets it
    names that the suite refuses to extend."""

    words: tuple[tuple[str, tuple[str, ...]], ...] = ()
    regions: tuple[tuple[str, Layer], ...] = ()
    refused: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordPaths:
    """The [records] table: where the design and the architecture record are."""

    design: str
    architecture: str


@dataclass(frozen=True, slots=True)
class Runtime:
    """A declared entry the repository can be run as, and the path patterns
    of the units it is made of."""

    name: str
    patterns: tuple[str, ...]
    # The declaration file that declares it, and the subtrees where a
    # nearer declaration's [override.runtimes] voids it.
    source: str = DECLARATION_PATH
    outside: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Declaration:
    """A repository's statement of its layers, runtimes, records, radar and
    exemptions: its governing declarations read as one, every path
    repository-root-relative. `governed` names the directory of each file
    ("" for the root's); a path under none of them is an undeclared
    subtree. `records` and `radar` are the root's; `record_scopes` and
    `radar_scopes` hold each nearer file's, by its directory, and the
    nearest governing one applies to a path. Declaration.none is the value
    for a repository that has none in force anywhere.
    """

    declared: bool = True
    layers: Layers = field(default_factory=Layers)
    exemptions: tuple[Exemption, ...] = ()
    refused_exemptions: tuple[RefusedExemption, ...] = ()
    vocabulary: VocabularyExtension = field(default_factory=VocabularyExtension)
    records: RecordPaths | None = None
    radar: str | None = None
    runtimes: tuple[Runtime, ...] = ()
    governed: tuple[str, ...] = ("",)
    record_scopes: tuple[tuple[str, RecordPaths], ...] = ()
    radar_scopes: tuple[tuple[str, str], ...] = ()

    none: ClassVar[Declaration]

    def governs(self, path: str) -> bool:
        """Whether a governing declaration reaches the path."""
        return any(is_under(path, directory) for directory in self.governed)

    def records_for(self, path: str) -> RecordPaths | None:
        """The design records the nearest governing file naming them names."""
        return _nearest(path, self.record_scopes, self.records)

    def radar_for(self, path: str) -> str | None:
        """The radar the nearest governing file naming one names."""
        return _nearest(path, self.radar_scopes, self.radar)


Declaration.none = Declaration(declared=False, governed=())


Scoped = TypeVar("Scoped")


def is_under(path: str, directory: str) -> bool:
    """Whether a repository path is in a directory's subtree ("" is the
    root's)."""
    return directory == "" or path.startswith(f"{directory}/")


def _nearest(
    path: str, scopes: Sequence[tuple[str, Scoped]], root: Scoped | None
) -> Scoped | None:
    found = [(len(d), value) for d, value in scopes if is_under(path, d)]
    if not found:
        return root
    return max(found, key=lambda hit: hit[0])[1]


@dataclass(frozen=True, slots=True)
class DeclarationUnreadable:
    """The outcome of a declaration that cannot be read, with the reason."""

    reason: str


# A revision's adherence.toml: its bytes, None where the file is absent, or
# why it cannot be read.
DeclarationText = bytes | None | DeclarationUnreadable


# --- Approvals (ReviewPort's answers, as values) -----------------------------


@dataclass(frozen=True, slots=True)
class Approval:
    """One approving review: who gave it, and the commit it reviewed."""

    reviewer: str
    commit: str


@dataclass(frozen=True, slots=True)
class Landing:
    """The pull request that landed a commit: its author, its approving
    reviews, adherence.toml at each commit they reviewed as the code host
    gives it, so a PR head no checkout can fetch (a squash or rebase
    landing) is still read (one it does not give is read from the
    repository), and the account that merged it, None when the code host
    names none."""

    author: str
    approvals: tuple[Approval, ...] = ()
    reviewed: tuple[tuple[str, DeclarationText], ...] = ()
    merged_by: str | None = None


@dataclass(frozen=True, slots=True)
class NoLandingPR:
    """No pull request landed the commit: a direct push or a bypass."""

    commit: str


@dataclass(frozen=True, slots=True)
class Unknown:
    """The place the run happens cannot know who approved a landing; the
    landed declaration stands there."""

    reason: str


@dataclass(frozen=True, slots=True)
class ReviewsUnavailable:
    """The code host's reviews could not be read, with the reason; counted
    as no approvals."""

    reason: str


# --- Predicates --------------------------------------------------------------


def is_literal(pattern: str) -> bool:
    """Whether a layer pattern names one path rather than a glob."""
    return not GLOB_CHARACTERS & set(pattern)


def matches(pattern: str, path: str) -> bool:
    """Whether a repository path matches a layer pattern: `**` as a whole
    segment crosses directories (zero or more before a further segment, one
    or more at the end), `*`, `?` and `[...]` stay within one segment.

    Matched segment by segment in one pass over a table, never by a
    backtracking regex: the pattern is the declaration author's, and its
    cost must stay linear in the pattern times the path."""
    parts = pattern.split("/")
    segments = path.split("/")
    # tail[j]: does parts[i:] match segments[j:], for the row i being built.
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


def is_declared_check(name: str | None) -> bool:
    """Whether the check named is one of the Declared quality's."""
    check = check_named(name) if name else None
    return check is not None and check.quality is Quality.DECLARED


# --- Pure helpers ------------------------------------------------------------


def marker_regions(path: str, text: str, vocabulary: Vocabulary) -> tuple[Region, ...]:
    """The regions a file's section markers open: from each marker the
    vocabulary knows to the line before the next marker, or the end of the
    file. A marker it does not know closes the region before it."""
    lines = source_lines(text)
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
    file; a widened path, which only a file nothing else covers has, is that
    file's layer; a literal path beats a glob; a longer glob beats a shorter
    one.
    """
    if line is not None:
        for region in (*declaration.layers.regions, *found):
            if region.holds(path, line):
                return region.layer
    for layer, created in declaration.layers.widened:
        if created == path:
            return layer
    voided = {
        index for index, subtree in declaration.layers.voided if is_under(path, subtree)
    }
    hits = [
        (is_literal(pattern), len(pattern), layer)
        for index, (layer, pattern) in enumerate(declaration.layers.globs)
        if index not in voided and matches(pattern, path)
    ]
    if not hits:
        return None
    return max(hits, key=lambda hit: (hit[0], hit[1]))[2]


def _region(
    entry: object, number: int, name: str
) -> Region | str | DeclarationUnreadable:
    """One regions entry: a Region by lines, the path of a marker file, or
    why it cannot be read."""
    where = f"{name}: layers region {number}"
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


def _layers(value: object, name: str) -> Layers | DeclarationUnreadable:
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{name}: layers is a table")
    globs: list[tuple[Layer, str]] = []
    regions: list[Region] = []
    marker_files: list[str] = []
    for key, patterns in value.items():
        if key == REGIONS_KEY:
            if not isinstance(patterns, list):
                return DeclarationUnreadable(f"{name}: layers.regions is a list")
            for number, entry in enumerate(patterns, start=1):
                region = _region(entry, number, name)
                if isinstance(region, DeclarationUnreadable):
                    return region
                if isinstance(region, Region):
                    regions.append(region)
                else:
                    marker_files.append(region)
            continue
        layer = LAYER_NAMES.get(key)
        if layer is None:
            return DeclarationUnreadable(f"{name}: {key} is not a layer")
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) for p in patterns
        ):
            return DeclarationUnreadable(
                f"{name}: layers.{key} is a list of path patterns"
            )
        globs.extend((layer, pattern) for pattern in patterns)
    return Layers(tuple(globs), tuple(regions), tuple(marker_files))


def _text_field(entry: Mapping[str, object], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) and value else None


def _exemption(
    entry: object, number: int, name: str
) -> Exemption | DeclarationUnreadable:
    """One [[exemptions]] entry, or why it cannot be read."""
    where = f"{name}: exemption {number}"
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


def _exemptions(
    value: object, name: str
) -> tuple[Exemption, ...] | DeclarationUnreadable:
    if not isinstance(value, list):
        return DeclarationUnreadable(
            f"{name}: exemptions is an array of tables ([[exemptions]])"
        )
    parsed: list[Exemption] = []
    for number, entry in enumerate(value, start=1):
        exemption = _exemption(entry, number, name)
        if isinstance(exemption, DeclarationUnreadable):
            return exemption
        parsed.append(exemption)
    return tuple(parsed)


def _vocabulary_regions(value: object) -> tuple[tuple[str, Layer], ...] | str:
    """The [vocabulary.regions] table, or why it cannot be read."""
    if not isinstance(value, dict):
        return "vocabulary.regions is a table of marker = layer"
    regions: list[tuple[str, Layer]] = []
    for marker, name in value.items():
        layer = LAYER_NAMES.get(name) if isinstance(name, str) else None
        if layer is None:
            return f"vocabulary.regions: {marker} names no known layer"
        regions.append((marker.lower(), layer))
    return tuple(regions)


def _vocabulary(
    value: object, name: str
) -> VocabularyExtension | DeclarationUnreadable:
    """The [vocabulary] table, or why it cannot be read."""
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{name}: vocabulary is a table")
    words: list[tuple[str, tuple[str, ...]]] = []
    regions: tuple[tuple[str, Layer], ...] = ()
    refused: list[str] = []
    for key, entry in value.items():
        if key == REGIONS_KEY:
            found = _vocabulary_regions(entry)
            if isinstance(found, str):
                return DeclarationUnreadable(f"{name}: {found}")
            regions = found
        elif key not in WORD_SETS:
            return DeclarationUnreadable(f"{name}: vocabulary.{key} is no vocabulary")
        elif not isinstance(entry, list) or not all(
            isinstance(word, str) and word for word in entry
        ):
            return DeclarationUnreadable(f"{name}: vocabulary.{key} is a list of words")
        elif key not in FINDING_SETS:
            refused.append(key)
        else:
            words.append((key, tuple(entry)))
    return VocabularyExtension(tuple(words), regions, tuple(refused))


def extended(vocabulary: Vocabulary, extension: VocabularyExtension) -> Vocabulary:
    """The vocabulary with the extension's words and region markers added:
    a word set only grows, and a marker the vocabulary already maps keeps
    its layer."""
    grown = {
        name: getattr(vocabulary, name) | frozenset(added)
        for name, added in extension.words
    }
    regions = {
        **{marker: layer for marker, layer in extension.regions},
        **vocabulary.regions,
    }
    return replace(vocabulary, regions=regions, **grown)


def with_overrides(parameters: Parameters, declaration: Declaration) -> Parameters:
    """The parameters a run under the declaration is given: the shipped ones
    with the declaration's overrides merged in, which only extend."""
    return replace(
        parameters, vocabulary=extended(parameters.vocabulary, declaration.vocabulary)
    )


def _records(value: object, name: str) -> RecordPaths | DeclarationUnreadable:
    """The [records] table, or why it cannot be read: it names both records,
    each by a path, and nothing else."""
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{name}: records is a table")
    unknown = sorted(set(value) - set(RECORD_KEYS))
    if unknown:
        return DeclarationUnreadable(
            f"{name}: records has unknown key(s): {', '.join(unknown)}"
        )
    if not all(_text_field(value, key) for key in RECORD_KEYS):
        return DeclarationUnreadable(
            f"{name}: records names the design and the architecture "
            "record, each by a path"
        )
    return RecordPaths(design=value["design"], architecture=value["architecture"])


def _radar(value: object, name: str) -> str | DeclarationUnreadable:
    """The [radar] table, or why it cannot be read: it names the radar by
    one path, and nothing else."""
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{name}: radar is a table")
    unknown = sorted(set(value) - {RADAR_KEY})
    if unknown:
        return DeclarationUnreadable(
            f"{name}: radar has unknown key(s): {', '.join(unknown)}"
        )
    path = _text_field(value, RADAR_KEY)
    if path is None:
        return DeclarationUnreadable(f"{name}: radar names the radar by a path")
    return path


def _runtimes(value: object, name: str) -> tuple[Runtime, ...] | DeclarationUnreadable:
    """The [runtimes] table, or why it cannot be read: each runtime names a
    list of path patterns."""
    if not isinstance(value, dict):
        return DeclarationUnreadable(f"{name}: runtimes is a table")
    runtimes: list[Runtime] = []
    for runtime, patterns in value.items():
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) for p in patterns
        ):
            return DeclarationUnreadable(
                f"{name}: runtimes.{runtime} is a list of path patterns"
            )
        runtimes.append(Runtime(runtime, tuple(patterns)))
    return tuple(runtimes)


def widened(
    *,
    in_force: Declaration,
    proposed: Declaration | DeclarationUnreadable,
    created: Collection[str],
) -> Declaration:
    """The declaration in force with the proposed one's widening merged in:
    its layer assignments for the files the change created that the
    declaration in force leaves uncovered, each matched by its path alone
    -- a created path holding glob characters must never reach a file the
    change did not create. Nothing else of the proposed declaration is
    taken, so it can only add checks."""
    if not in_force.declared or not isinstance(proposed, Declaration):
        return in_force
    uncovered = [
        p
        for p in sorted(created)
        if in_force.governs(p) and layer_of(p, None, in_force) is None
    ]
    paths = tuple(
        (layer, path)
        for path in uncovered
        if (layer := layer_of(path, None, proposed)) is not None
    )
    regions = tuple(r for r in proposed.layers.regions if r.path in uncovered)
    markers = tuple(p for p in proposed.layers.marker_files if p in uncovered)
    layers = in_force.layers
    return replace(
        in_force,
        layers=replace(
            layers,
            regions=(*layers.regions, *regions),
            marker_files=(*layers.marker_files, *markers),
            widened=(*layers.widened, *paths),
        ),
    )


def _silencing(finding: Finding, declaration: Declaration) -> Exemption | None:
    """The first exemption that silences the finding: one dismissing it by
    its identity, or one naming its check and a unit pattern its path
    matches."""
    return next(
        (
            e
            for e in declaration.exemptions
            if e.reaches(finding.unit.path)
            and (
                e.finding == finding.identity
                or (
                    e.check == finding.check.name
                    and e.unit is not None
                    and matches(e.unit, finding.unit.path)
                )
            )
        ),
        None,
    )


def exempted(
    findings: tuple[Finding, ...], declaration: Declaration
) -> tuple[tuple[Finding, ...], tuple[Notice, ...]]:
    """Each finding, marked with the reason of the exemption that silences
    it; and a notice per exemption that silenced one, naming it and its
    reason beside the check."""
    marked: list[Finding] = []
    applied: list[Exemption] = []
    for finding in findings:
        exemption = _silencing(finding, declaration)
        if exemption is None:
            marked.append(finding)
            continue
        marked.append(replace(finding, exempt=exemption.reason))
        if exemption not in applied:
            applied.append(exemption)
    return tuple(marked), tuple(
        Notice(f"exemption applied: {exemption_target(e)}: {e.reason}") for e in applied
    )


def exemption_target(exemption: Exemption) -> str:
    """What an exemption silences, as a reviewer reads it."""
    return exemption.finding or f"{exemption.check} on {exemption.unit}"


def refusal_notices(declaration: Declaration) -> tuple[Notice, ...]:
    """A notice per exemption and per vocabulary the declaration states and
    the suite refuses, naming what it would exempt or extend and why it is
    refused."""
    return (
        *(
            Notice(
                f"exemption refused: {r.exemption.check} on {r.exemption.unit}: "
                f"{r.reason}"
            )
            for r in declaration.refused_exemptions
        ),
        *(
            Notice(f"vocabulary refused: {key}: {VOCABULARY_REFUSAL}")
            for key in declaration.vocabulary.refused
        ),
    )


@dataclass(frozen=True, slots=True)
class DeclarationFile:
    """One adherence.toml read on its own: where it is, what it states with
    every path made repository-root-relative, and which sections it defines
    plainly and which it writes under [override]."""

    path: str
    declaration: Declaration
    defines: frozenset[str] = frozenset()
    overrides: frozenset[str] = frozenset()

    @property
    def directory(self) -> str:
        return directory_of(self.path)

    def has(self, section: str) -> bool:
        return section in self.defines or section in self.overrides


def directory_of(path: str) -> str:
    """The directory holding a repository path; "" for the root."""
    return path.rpartition("/")[0]


def escapes(path: str) -> bool:
    """Whether a path a declaration names leaves the declaration's
    directory: a leading slash, or any `..` segment."""
    return path.startswith("/") or ".." in path.split("/")


def _under(directory: str, path: str) -> str:
    return f"{directory}/{path}" if directory else path


def _moved(exemption: Exemption, directory: str) -> Exemption:
    """An exemption of a file in the directory: its unit glob resolved
    under it, and applying only within it."""
    unit = exemption.unit
    return replace(
        exemption,
        unit=_under(directory, unit) if unit is not None else None,
        within=directory,
    )


def _relocated(
    declaration: Declaration, directory: str, name: str
) -> Declaration | DeclarationUnreadable:
    """The declaration with every path it names resolved under its file's
    directory, or why one escapes it."""
    layers = declaration.layers
    named = [
        *(p for _, p in layers.globs),
        *(r.path for r in layers.regions),
        *layers.marker_files,
        *(p for r in declaration.runtimes for p in r.patterns),
        *(e.unit for e in declaration.exemptions if e.unit is not None),
        *(
            e.exemption.unit
            for e in declaration.refused_exemptions
            if e.exemption.unit is not None
        ),
        *(
            (declaration.records.design, declaration.records.architecture)
            if declaration.records
            else ()
        ),
        *((declaration.radar,) if declaration.radar else ()),
    ]
    escaping = next((p for p in named if escapes(p)), None)
    if escaping is not None:
        return DeclarationUnreadable(f"{name}: {escaping} {ESCAPES}")

    at = directory
    return replace(
        declaration,
        layers=Layers(
            tuple((layer, _under(at, p)) for layer, p in layers.globs),
            tuple(replace(r, path=_under(at, r.path)) for r in layers.regions),
            tuple(_under(at, p) for p in layers.marker_files),
        ),
        exemptions=tuple(_moved(e, at) for e in declaration.exemptions),
        refused_exemptions=tuple(
            replace(r, exemption=_moved(r.exemption, at))
            for r in declaration.refused_exemptions
        ),
        records=(
            RecordPaths(
                _under(at, declaration.records.design),
                _under(at, declaration.records.architecture),
            )
            if declaration.records
            else None
        ),
        radar=_under(at, declaration.radar) if declaration.radar else None,
        runtimes=tuple(
            Runtime(r.name, tuple(_under(at, p) for p in r.patterns), source=name)
            for r in declaration.runtimes
        ),
        governed=(directory,),
    )


def _document(text: bytes, name: str) -> dict[str, object] | DeclarationUnreadable:
    try:
        return tomllib.loads(text.decode("utf-8"))
    except UnicodeDecodeError as error:
        return DeclarationUnreadable(f"{name} is not utf-8: {error}")
    except tomllib.TOMLDecodeError as error:
        return DeclarationUnreadable(f"{name}: {error}")
    except ValueError as error:
        # tomllib's own conversions (an integer past Python's digit limit)
        # raise a plain ValueError rather than TOMLDecodeError.
        return DeclarationUnreadable(f"{name}: {error}")
    except RecursionError:
        return DeclarationUnreadable(
            f"{name} is nested deeper than the parser can follow"
        )


def _sections(
    document: Mapping[str, object], name: str
) -> tuple[dict[str, object], frozenset[str], frozenset[str]] | DeclarationUnreadable:
    """The file's sections, plain and under [override], as one table; and
    which it defines and which it overrides."""
    unknown = sorted(set(document) - TABLES - {OVERRIDE})
    if unknown:
        return DeclarationUnreadable(f"{name}: unknown table(s): {', '.join(unknown)}")
    overriding = document.get(OVERRIDE, {})
    if not isinstance(overriding, dict):
        return DeclarationUnreadable(f"{name}: override is a table of sections")
    unknown = sorted(set(overriding) - TABLES)
    if unknown:
        return DeclarationUnreadable(
            f"{name}: unknown override section(s): {', '.join(unknown)}"
        )
    both = sorted(set(overriding) & set(document))
    if both:
        return DeclarationUnreadable(
            f"{name}: [{both[0]}] is both defined and overridden; write one"
        )
    defines = frozenset(set(document) - {OVERRIDE})
    sections = {**{k: v for k, v in document.items() if k != OVERRIDE}, **overriding}
    return sections, defines, frozenset(overriding)


def _stated(
    sections: Mapping[str, object], name: str
) -> Declaration | DeclarationUnreadable:
    """What one file's sections state, its paths as written."""
    layers = _layers(sections.get("layers", {}), name)
    if isinstance(layers, DeclarationUnreadable):
        return layers
    exemptions = _exemptions(sections.get("exemptions", []), name)
    if isinstance(exemptions, DeclarationUnreadable):
        return exemptions
    vocabulary = _vocabulary(sections.get("vocabulary", {}), name)
    if isinstance(vocabulary, DeclarationUnreadable):
        return vocabulary
    records = _records(sections["records"], name) if "records" in sections else None
    if isinstance(records, DeclarationUnreadable):
        return records
    radar = _radar(sections["radar"], name) if "radar" in sections else None
    if isinstance(radar, DeclarationUnreadable):
        return radar
    runtimes = _runtimes(sections.get("runtimes", {}), name)
    if isinstance(runtimes, DeclarationUnreadable):
        return runtimes
    return Declaration(
        layers=layers,
        exemptions=tuple(e for e in exemptions if not is_declared_check(e.check)),
        refused_exemptions=tuple(
            RefusedExemption(e, DECLARED_REFUSAL)
            for e in exemptions
            if is_declared_check(e.check)
        ),
        vocabulary=vocabulary,
        records=records,
        radar=radar,
        runtimes=runtimes,
    )


def parse_file(path: str, text: bytes) -> DeclarationFile | DeclarationUnreadable:
    """One adherence.toml's bytes, read on their own: what they state with
    every path resolved under the file's directory, or why they cannot be
    read."""
    document = _document(text, path)
    if isinstance(document, DeclarationUnreadable):
        return document
    sections = _sections(document, path)
    if isinstance(sections, DeclarationUnreadable):
        return sections
    table, defines, overrides = sections
    stated = _stated(table, path)
    if isinstance(stated, DeclarationUnreadable):
        return stated
    relocated = _relocated(stated, directory_of(path), path)
    if isinstance(relocated, DeclarationUnreadable):
        return relocated
    return DeclarationFile(path, relocated, defines, overrides)


def parse_declaration(
    text: bytes, directory: str = ""
) -> Declaration | DeclarationUnreadable:
    """The Declaration one adherence.toml's bytes state, the file in the
    directory given, read as its own governing declarations; or why they
    cannot be read."""
    parsed = parse_file(_under(directory, DECLARATION_PATH), text)
    if isinstance(parsed, DeclarationUnreadable):
        return parsed
    return governing_declarations((parsed,), ())


# --- Governing declarations: the files read as one ---------------------------


def _depth(file: DeclarationFile) -> tuple[int, str]:
    directory = file.directory
    return (directory.count("/") + 1 if directory else 0, file.path)


def _above(
    file: DeclarationFile, files: Sequence[DeclarationFile]
) -> list[DeclarationFile]:
    """The files governing the file's directory from above, nearest first."""
    return sorted(
        (
            f
            for f in files
            if f.directory != file.directory and is_under(file.directory, f.directory)
        ),
        key=_depth,
        reverse=True,
    )


def _illegal(files: Sequence[DeclarationFile]) -> DeclarationUnreadable | None:
    """The first section a file defines that a file above already defines,
    for a single-valued section, or overrides where nothing above defines
    it."""
    for file in files:
        above = _above(file, files)
        for section in sorted(file.defines & SINGLE_VALUED):
            first = next((f for f in above if f.has(section)), None)
            if first is not None:
                return DeclarationUnreadable(
                    f"{first.path} and {file.path} both define [{section}]: a "
                    f"nearer declaration replaces it only under [override.{section}]"
                )
        for section in sorted(file.overrides):
            if not any(f.has(section) for f in above):
                return DeclarationUnreadable(
                    f"{file.path}: [override.{section}] overrides nothing: no "
                    f"declaration above it defines [{section}]"
                )
    return None


def _voiding(
    file: DeclarationFile, section: str, files: Sequence[DeclarationFile]
) -> tuple[str, ...]:
    """The subtrees below the file where a nearer file overrides the
    section, so the file's entries for it do not apply there."""
    return tuple(
        f.directory
        for f in files
        if section in f.overrides
        and f.directory != file.directory
        and is_under(f.directory, file.directory)
    )


def _merged_exemptions(exemptions: Sequence[Exemption]) -> tuple[Exemption, ...]:
    """One exemption per thing exempted: the same one from two files is one
    carrying both reasons, applying wherever either does."""
    merged: dict[tuple[str | None, str | None, str | None], Exemption] = {}
    for e in exemptions:
        key = (e.check, e.unit, e.finding)
        kept = merged.get(key)
        if kept is None:
            merged[key] = e
            continue
        shallower = min((kept.within, e.within), key=len)
        merged[key] = replace(
            kept,
            reason=kept.reason
            if e.reason == kept.reason
            else f"{kept.reason}; {e.reason}",
            within=shallower,
            outside=tuple(d for d in kept.outside if d in e.outside),
        )
    return tuple(merged.values())


def _layers_merged(files: Sequence[DeclarationFile]) -> Layers:
    globs: list[tuple[Layer, str]] = []
    voided: list[tuple[int, str]] = []
    regions: list[Region] = []
    markers: list[str] = []
    for file in files:
        layers = file.declaration.layers
        cut = _voiding(file, "layers", files)
        for glob in layers.globs:
            voided.extend((len(globs), d) for d in cut)
            globs.append(glob)
        regions.extend(
            r for r in layers.regions if not any(is_under(r.path, d) for d in cut)
        )
        markers.extend(
            p for p in layers.marker_files if not any(is_under(p, d) for d in cut)
        )
    return Layers(tuple(globs), tuple(regions), tuple(markers), (), tuple(voided))


def _vocabulary_merged(files: Sequence[DeclarationFile]) -> VocabularyExtension:
    extensions = [f.declaration.vocabulary for f in files]
    return VocabularyExtension(
        tuple(w for e in extensions for w in e.words),
        tuple(r for e in extensions for r in e.regions),
        tuple(dict.fromkeys(k for e in extensions for k in e.refused)),
    )


def _assigned(path: str, file: DeclarationFile) -> frozenset[Layer]:
    """The layers one file assigns a real path by its own precedence: its
    regions of the file, else its glob or literal assignment."""
    declaration = file.declaration
    regions = frozenset(r.layer for r in declaration.layers.regions if r.path == path)
    if regions:
        return regions
    layer = layer_of(path, None, declaration)
    return frozenset() if layer is None else frozenset({layer})


def _conflict(
    files: Sequence[DeclarationFile], tree: Collection[str]
) -> DeclarationUnreadable | None:
    """The first real path two governing files place in two layers, with
    no [override.layers] between them."""
    for path in sorted(tree):
        governing = sorted(
            (f for f in files if is_under(path, f.directory)), key=_depth
        )
        cut = [f for f in governing if "layers" in f.overrides]
        if cut:
            governing = governing[governing.index(cut[-1]) :]
        placed = [(f, layers) for f in governing if (layers := _assigned(path, f))]
        for (first, one), (second, other) in itertools.combinations(placed, 2):
            if one != other:
                return DeclarationUnreadable(
                    f"{first.path} and {second.path} place {path} in two layers "
                    f"([layers]): {_named(one)} and {_named(other)}"
                )
    return None


def _named(layers: frozenset[Layer]) -> str:
    return ", ".join(sorted(layer.value for layer in layers))


def governing_declarations(
    files: Sequence[DeclarationFile], tree: Collection[str]
) -> Declaration | DeclarationUnreadable:
    """The declaration files read as one (DESIGN.ARCH-ADHERENCE.md, The
    declaration): layers, runtimes, exemptions and vocabulary a union, each
    file's entries void below a nearer file that overrides the section; a
    single-valued section the nearest governing file's that names it. A
    file that defines a single-valued section a file above it defines, an
    override of nothing, and two files that place one real path of `tree`
    in two layers are each a declaration that cannot be read, naming the
    files. No files is Declaration.none."""
    if not files:
        return Declaration.none
    ordered = sorted(files, key=_depth)
    refused = _illegal(ordered) or (
        _conflict(ordered, tree) if len(ordered) > 1 else None
    )
    if refused is not None:
        return refused
    root = next((f for f in ordered if f.directory == ""), None)
    return Declaration(
        layers=_layers_merged(ordered),
        exemptions=_merged_exemptions(
            [
                replace(e, outside=_voiding(f, "exemptions", ordered))
                for f in ordered
                for e in f.declaration.exemptions
            ]
        ),
        refused_exemptions=tuple(
            r for f in ordered for r in f.declaration.refused_exemptions
        ),
        vocabulary=_vocabulary_merged(ordered),
        records=root.declaration.records if root else None,
        radar=root.declaration.radar if root else None,
        runtimes=tuple(
            replace(r, outside=_voiding(f, "runtimes", ordered))
            for f in ordered
            for r in f.declaration.runtimes
        ),
        governed=tuple(f.directory for f in ordered),
        record_scopes=tuple(
            (f.directory, f.declaration.records)
            for f in ordered
            if f.directory and f.declaration.records is not None
        ),
        radar_scopes=tuple(
            (f.directory, f.declaration.radar)
            for f in ordered
            if f.directory and f.declaration.radar is not None
        ),
    )


# --- The declaration in force: approval counting -----------------------------
#
# Which landed revision of adherence.toml is in force (ARCHITECTURE.ARCH-
# ADHERENCE.md, Use-case surface: An unapproved declaration is not in
# force). The use case walks the landings newest first and passes each, as
# values, with the base's CODEOWNERS; this sub-component does the counting.

# Where GitHub looks for CODEOWNERS, in its order; the first found is read.
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

# An approval by the PR's author is refused, whoever the author is; an owner
# who authored the edit counts by merging it (design Key Decisions, An owner
# who is the author).
AUTHOR_REFUSAL = (
    "the reviewer is the pull request's author, and an author cannot approve "
    "their own declaration edit; a code owner who authored it counts by "
    "merging it"
)


@dataclass(frozen=True, slots=True)
class CodeOwners:
    """The base's CODEOWNERS entries in file order: each pattern and the
    owners it names. The last entry matching a path names its owners."""

    entries: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def owners_of(self, path: str) -> tuple[str, ...]:
        """The owners the last entry matching the path names; none when no
        entry matches."""
        return next(
            (
                owners
                for pattern, owners in reversed(self.entries)
                if codeowners_matches(pattern, path)
            ),
            (),
        )


@dataclass(frozen=True, slots=True)
class LandedRevision:
    """One landing of adherence.toml on the base's history, as values: the
    commit, ReviewPort's answer for it, the declaration's text there, and
    the text at each commit an approval reviewed (one missing was not
    read)."""

    commit: str
    answer: Landing | NoLandingPR | Unknown | ReviewsUnavailable
    text: DeclarationText = None
    reviewed: tuple[tuple[str, DeclarationText], ...] = ()
    path: str = DECLARATION_PATH


@dataclass(frozen=True, slots=True)
class Counting:
    """Whether a landing is in force, and the notices that say why not."""

    in_force: bool
    notices: tuple[Notice, ...] = ()


def codeowners_matches(pattern: str, path: str) -> bool:
    """Whether a CODEOWNERS pattern names a repository path, read as
    gitignore reads it: a leading or inner slash anchors it at the root,
    a pattern with neither matches at any depth, a trailing slash names a
    directory, and a directory's pattern names everything under it."""
    body = pattern.rstrip("/")
    directory = pattern.endswith("/")
    if not body:
        return False
    anchored = "/" in body
    body = body.lstrip("/")
    if not anchored:
        body = f"**/{body}"
    under = matches(f"{body}/**", path)
    return under if directory else matches(body, path) or under


def is_user_owner(owner: str) -> bool:
    """Whether a CODEOWNERS owner names one user (`@login`), not a team
    (`@org/team`) or an email address."""
    return owner.startswith("@") and "/" not in owner and len(owner) > 1


def is_same_login(one: str, other: str) -> bool:
    """Whether two code-host logins name the same account; logins ignore
    letter case."""
    return one.casefold() == other.casefold()


def parse_codeowners(text: bytes) -> CodeOwners:
    """The CODEOWNERS entries the bytes state: a pattern and its owners per
    line, comments and blank lines left out."""
    entries: list[tuple[str, tuple[str, ...]]] = []
    for line in text.decode("utf-8", "replace").splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        owners = tuple(
            itertools.takewhile(lambda word: not word.startswith("#"), words[1:])
        )
        entries.append((words[0], owners))
    return CodeOwners(tuple(entries))


def _short(commit: str) -> str:
    return commit[:12]


def _skipped(revision: LandedRevision, why: str) -> Notice:
    return Notice(
        f"{revision.path} landed at {_short(revision.commit)}: {why}; not in force"
    )


def _refusal(
    approval: Approval,
    *,
    author: str,
    owners: Collection[str],
    revision: LandedRevision,
) -> str | None:
    """Why an approval does not count, or None when it does."""
    if is_same_login(approval.reviewer, author):
        return AUTHOR_REFUSAL
    if not any(is_same_login(f"@{approval.reviewer}", o) for o in owners):
        return f"not a code owner of {revision.path} by the base's CODEOWNERS"
    landed = revision.text
    text = dict(revision.reviewed).get(
        approval.commit, DeclarationUnreadable("not read")
    )
    if isinstance(landed, DeclarationUnreadable):
        return f"the landed {revision.path} cannot be read: {landed.reason}"
    if isinstance(text, DeclarationUnreadable):
        return (
            f"the {revision.path} it reviewed at {_short(approval.commit)} "
            f"cannot be read: {text.reason}"
        )
    if text != landed:
        return (
            f"it reviewed {_short(approval.commit)}, whose {revision.path} "
            "differs from the landed one"
        )
    return None


def _in_force(revision: LandedRevision, why: str) -> Counting:
    return Counting(
        True,
        (
            Notice(
                f"{revision.path} landed at {_short(revision.commit)}: in force, {why}"
            ),
        ),
    )


def _merge_refusal(merger: str, owners: Collection[str], path: str) -> Notice | None:
    """Why a merge does not count, or None when it does: its merger is a
    user code owner of the declaration file by the base's CODEOWNERS."""
    if any(is_same_login(f"@{merger}", o) for o in owners):
        return None
    return Notice(
        f"merge by {merger} not counted: not a code owner of {path} "
        "by the base's CODEOWNERS"
    )


def owner_notices(
    codeowners: CodeOwners, path: str = DECLARATION_PATH
) -> tuple[Notice, ...]:
    """A notice per owner CODEOWNERS names for a declaration file that is a
    team or an email: it counts as no owner, since only a user is one. It
    is about the file, so a walk says it once, not once per landing."""
    owners = codeowners.owners_of(path)
    return tuple(
        Notice(
            f"CODEOWNERS entry {owner} for {path} counts as no owner: "
            "only a user (@login) is an owner, never a team or an email"
        )
        for owner in owners
        if not is_user_owner(owner)
    )


def counted_landing(revision: LandedRevision, codeowners: CodeOwners) -> Counting:
    """Whether a landing of adherence.toml is in force: Unknown leaves the
    landed declaration standing; a landing is in force when one approval
    counts -- its reviewer not the PR's author, a user code owner of
    adherence.toml by the base's CODEOWNERS, and the commit it reviewed
    holding the landed bytes, so approve-then-push does not pass -- or,
    with none, when a user code owner merged it, the author included (the
    one-human repository); a notice names which counted. A landing
    attributable to no one but an author who is no code owner is not.
    Every other answer is skipped with a notice that says why. A team or
    email CODEOWNERS entry counts as no owner; `owner_notices` says so."""
    answer = revision.answer
    if isinstance(answer, Unknown):
        return Counting(True)
    if isinstance(answer, NoLandingPR):
        return Counting(
            False,
            (
                _skipped(
                    revision, "landed with no pull request (a direct push or a bypass)"
                ),
            ),
        )
    if isinstance(answer, ReviewsUnavailable):
        return Counting(
            False,
            (
                _skipped(
                    revision, f"its landing's reviews cannot be read: {answer.reason}"
                ),
            ),
        )
    owners = codeowners.owners_of(revision.path)
    users = tuple(o for o in owners if is_user_owner(o))
    refusals = [
        (
            approval,
            _refusal(approval, author=answer.author, owners=users, revision=revision),
        )
        for approval in answer.approvals
    ]
    counted = next((a for a, why in refusals if why is None), None)
    if counted is not None:
        return _in_force(revision, f"approved by {counted.reviewer}")
    merge = (
        None
        if answer.merged_by is None
        else _merge_refusal(answer.merged_by, users, revision.path)
    )
    if answer.merged_by is not None and merge is None:
        return _in_force(revision, f"merged by code owner {answer.merged_by}")
    return Counting(
        False,
        (
            *(
                Notice(f"approval by {approval.reviewer} not counted: {why}")
                for approval, why in refusals
            ),
            *(() if merge is None else (merge,)),
            _skipped(
                revision,
                f"landed in a pull request by {answer.author} with no counted "
                "approval and no code owner's merge",
            ),
        ),
    )
