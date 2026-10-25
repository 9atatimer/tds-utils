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

    options_objects are the parameter names that hold an options object in
    a language with no keyword-only parameters (JavaScript): such a
    parameter, like a destructured object's members, is passed by name, the
    options-object form of ports as keywords.
    """

    regions: Mapping[str, Layer]
    environment_reads: frozenset[str] = field(default_factory=frozenset)
    sleeps: frozenset[str] = field(default_factory=frozenset)
    stubs: frozenset[str] = field(default_factory=frozenset)
    options_objects: frozenset[str] = field(default_factory=frozenset)

    def reads_environment(self, chain: str) -> bool:
        """Whether a name chain is, or runs through, an environment read
        (`os.environ.get` runs through `os.environ`)."""
        parts = chain.split(".")
        return any(
            ".".join(parts[:end]) in self.environment_reads
            for end in range(1, len(parts) + 1)
        )

    def is_sleep(self, callee: str) -> bool:
        """Whether a callee waits, by its full dotted name or its last part."""
        return callee in self.sleeps or callee.split(".")[-1] in self.sleeps
