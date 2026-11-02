"""domain/parameters.py -- the tuned values a run is given.

Parameters bundles ThresholdPolicy, Vocabulary and Limits
(ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface); the composition root
supplies the shipped defaults and domain/declaration merges a
declaration's overrides in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from adherence.domain.model import CodeLanguage, Layer
from adherence.domain.questions import ThresholdPolicy


def _is_or_on(callee: str, name: str) -> bool:
    """Whether a callee is the name, or a chain or call on it."""
    return callee == name or callee.startswith((f"{name}.", f"{name}("))


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
    the dotted names that reach a process-wide instance; plain_types each
    language's own type names, which a signature names but which are no
    noun of the problem -- by language, since a name one language owns
    (TypeScript's `Record`) is a noun of the problem in another.

    options_objects are the parameter names that hold an options object in
    a language with no keyword-only parameters (JavaScript): such a
    parameter, like a destructured object's members, is passed by name, the
    options-object form of ports as keywords. tests are the callees that
    declare a test case and assertions those that assert (Vitest, Jest,
    node:test); a callee counts when it is one, or a chain or call on one
    (`test.only`, `expect(x).toBe`).

    abstract_markers are the bases and decorators (a full dotted name, or
    its last part) that make a placeholder body a declaration, not a stub.
    assertion_calls are the assertion APIs: a dotted name matches what a
    call resolves to (`pytest.raises`), a bare name a method called on a
    receiver the analyzer cannot resolve (`assert_called_once`, as a mock
    carries it); a definition of the measured repository never matches.
    placeholder_assertions are the asserted expressions, as written, that
    cannot tell a pass from a fail, beside any literal.
    standard_library is each language's top-level modules that ship with
    it, never a dependency (for TypeScript and JavaScript, node's built-in
    modules, bare and `node:`-prefixed); packages maps a top-level module
    to the name its package carries on a radar, where the two differ.
    """

    regions: Mapping[str, Layer]
    environment_reads: frozenset[str] = field(default_factory=frozenset)
    sleeps: frozenset[str] = field(default_factory=frozenset)
    stubs: frozenset[str] = field(default_factory=frozenset)
    options_objects: frozenset[str] = field(default_factory=frozenset)
    tests: frozenset[str] = field(default_factory=frozenset)
    assertions: frozenset[str] = field(default_factory=frozenset)
    vendors: frozenset[str] = field(default_factory=frozenset)
    model_ids: frozenset[str] = field(default_factory=frozenset)
    mechanism_calls: frozenset[str] = field(default_factory=frozenset)
    fakes: frozenset[str] = field(default_factory=frozenset)
    abstract_markers: frozenset[str] = field(default_factory=frozenset)
    assertion_calls: frozenset[str] = field(default_factory=frozenset)
    placeholder_assertions: frozenset[str] = field(default_factory=frozenset)
    standard_library: Mapping[CodeLanguage, frozenset[str]] = field(
        default_factory=dict
    )
    packages: Mapping[str, str] = field(default_factory=dict)
    clocks: frozenset[str] = field(default_factory=frozenset)
    callables: frozenset[str] = field(default_factory=frozenset)
    wire_formats: frozenset[str] = field(default_factory=frozenset)
    singletons: frozenset[str] = field(default_factory=frozenset)
    plain_types: Mapping[CodeLanguage, frozenset[str]] = field(default_factory=dict)

    def reads_environment(self, chain: str) -> bool:
        """Whether a name chain is, or runs through, an environment read
        (`os.environ.get` runs through `os.environ`)."""
        parts = chain.split(".")
        return any(
            ".".join(parts[:end]) in self.environment_reads
            for end in range(1, len(parts) + 1)
        )

    def declares_test(self, callee: str) -> bool:
        """Whether a callee declares a test case."""
        return any(_is_or_on(callee, name) for name in self.tests)

    def asserts(self, callee: str) -> bool:
        """Whether a callee asserts."""
        return any(_is_or_on(callee, name) for name in self.assertions)

    def is_plain(self, name: str, language: CodeLanguage | None) -> bool:
        """Whether a type name is the language's own; no name is plain in
        a unit of no language the suite measures."""
        if language is None:
            return False
        return name in self.plain_types.get(language, frozenset())

    def is_sleep(self, callee: str) -> bool:
        """Whether a callee waits, by its full dotted name or its last part."""
        return callee in self.sleeps or callee.split(".")[-1] in self.sleeps


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
