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
    names a model; mechanism_calls the callees (a full dotted name, as
    written) that reach the filesystem or load a module by name; fakes the
    name prefixes that mark an implementation of a port as a fake; clocks
    the type names that are a clock, and callables those that are a
    callable, in a parameter's annotation.
    wire_formats are the type names -- a wire format, or an SDK type or
    handle known by name -- that no use-case signature may carry; singletons
    the dotted names that reach a process-wide instance; plain_types the
    language's own type names, which a signature names but which are no
    noun of the problem.
    """

    regions: Mapping[str, Layer]
    environment_reads: frozenset[str] = field(default_factory=frozenset)
    sleeps: frozenset[str] = field(default_factory=frozenset)
    stubs: frozenset[str] = field(default_factory=frozenset)
    vendors: frozenset[str] = field(default_factory=frozenset)
    model_ids: frozenset[str] = field(default_factory=frozenset)
    mechanism_calls: frozenset[str] = field(default_factory=frozenset)
    fakes: frozenset[str] = field(default_factory=frozenset)
    clocks: frozenset[str] = field(default_factory=frozenset)
    callables: frozenset[str] = field(default_factory=frozenset)
    wire_formats: frozenset[str] = field(default_factory=frozenset)
    singletons: frozenset[str] = field(default_factory=frozenset)
    plain_types: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Limits:
    """The tuned bounds (ARCHITECTURE.ARCH-ADHERENCE.md, Parameters placed).

    evidence_bound is how many characters of the offending line a finding
    may quote.
    """

    evidence_bound: int


@dataclass(frozen=True, slots=True)
class Parameters:
    """The design's Parameters table as one value."""

    thresholds: ThresholdPolicy
    vocabulary: Vocabulary
    limits: Limits
