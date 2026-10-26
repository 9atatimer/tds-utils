"""domain/parameters.py -- the tuned values a run is given.

Parameters bundles ThresholdPolicy, Vocabulary and Limits
(ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface); the composition root
supplies the shipped defaults and domain/declaration merges a
declaration's overrides in. Only Vocabulary exists so far.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from adherence.domain.model import Layer


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """What counts as a marker of each kind (ARCHITECTURE.ARCH-ADHERENCE.md,
    Seams: Vocabulary); the composition root supplies the shipped defaults.

    regions maps a section marker's name, lower-cased, to the layer of the
    region it opens. environment_reads are the dotted names that read the
    process environment; sleeps the callees (a full dotted name, or its last
    part) that wait; stubs the placeholder forms a body that is nothing but
    one names (`pass`, `...`, `NotImplementedError`).
    """

    regions: Mapping[str, Layer]
    environment_reads: frozenset[str] = field(default_factory=frozenset)
    sleeps: frozenset[str] = field(default_factory=frozenset)
    stubs: frozenset[str] = field(default_factory=frozenset)
