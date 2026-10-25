"""domain/parameters.py -- the tuned values a run is given.

Parameters bundles ThresholdPolicy, Vocabulary and Limits
(ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface); the composition root
supplies the shipped defaults and domain/declaration merges a
declaration's overrides in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from adherence.domain.model import Layer
from adherence.domain.questions import ThresholdPolicy


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """What counts as a marker of each kind (ARCHITECTURE.ARCH-ADHERENCE.md,
    Seams: Vocabulary); the composition root supplies the shipped defaults.

    regions maps a section marker's name, lower-cased, to the layer of the
    region it opens. environment_reads are the dotted names that read the
    process environment; sleeps the callees (a full dotted name, or its last
    part) that wait; stubs the placeholder forms a body that is nothing but
    one names (`pass`, `...`, `NotImplementedError`). vendors are the
    modules (a top-level name, or a dotted prefix) that are a vendor, an SDK,
    the filesystem or the network; model_ids the prefixes of a string that
    names a model; fakes the name prefixes that mark an implementation of a
    port as a fake.

    abstract_markers are the bases and decorators (a full dotted name, or
    its last part) that make a placeholder body a declaration, not a stub.
    assertion_calls are the callees (a full dotted name, or its last part)
    that assert, as `pytest.raises` does; placeholder_assertions the
    asserted expressions, as written, that cannot tell a pass from a fail.
    """

    regions: Mapping[str, Layer]
    environment_reads: frozenset[str] = field(default_factory=frozenset)
    sleeps: frozenset[str] = field(default_factory=frozenset)
    stubs: frozenset[str] = field(default_factory=frozenset)
    vendors: frozenset[str] = field(default_factory=frozenset)
    model_ids: frozenset[str] = field(default_factory=frozenset)
    fakes: frozenset[str] = field(default_factory=frozenset)
    abstract_markers: frozenset[str] = field(default_factory=frozenset)
    assertion_calls: frozenset[str] = field(default_factory=frozenset)
    placeholder_assertions: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Limits:
    """The tuned bounds (ARCHITECTURE.ARCH-ADHERENCE.md, Parameters placed).

    evidence_bound is how many characters of the offending line a finding
    may quote. complexity_ceiling is the per-function complexity above which
    Complexity finds; None, when no ceiling is supplied, leaves the check as
    coverage. duplication_ceiling is the clone size, in lines, above which
    Duplication finds; None likewise leaves it as coverage.
    """

    evidence_bound: int
    complexity_ceiling: int | None = None
    duplication_ceiling: int | None = None


@dataclass(frozen=True, slots=True)
class Parameters:
    """The design's Parameters table as one value."""

    thresholds: ThresholdPolicy
    vocabulary: Vocabulary
    limits: Limits
