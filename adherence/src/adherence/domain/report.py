"""domain/report.py -- a run's outcome, and its identity.

The checks that ran and every finding each produced (DESIGN.ARCH-
ADHERENCE.md, Measurement). Presenters shape it; it derives no number
from the findings. Its identity -- suite version, parameters digest,
declaration digest, analyzer set, judge availability -- says which
reports are comparable (ARCHITECTURE.ARCH-ADHERENCE.md, Module map).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding, Notice, normalised
from adherence.domain.model import Unit
from adherence.domain.qualities import CATALOG, Check, Quality
from adherence.domain.questions import Abstention, Ask, Pass

# --- Constants ---------------------------------------------------------------

# The suite's version, as adherence/pyproject.toml states it.
SUITE_VERSION = "0.1.0"
# Why a check a bounded run was ended before is coverage.
ENDED = "did not finish before the deadline"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportIdentity:
    """What makes two reports comparable: the suite, the parameters, the
    declaration, the measured languages and the judge's availability."""

    suite: str
    parameters: str
    declaration: str
    analyzers: tuple[str, ...]
    judge: str

    @property
    def digest(self) -> str:
        """One digest of the whole identity, the key a report is kept by."""
        return fingerprint(self)

    def differences(self, other: ReportIdentity) -> tuple[str, ...]:
        """The parts of the identity in which the other differs, by name."""
        return tuple(
            f.name
            for f in dataclasses.fields(self)
            if getattr(self, f.name) != getattr(other, f.name)
        )


@dataclass(frozen=True, slots=True)
class BodyDigest:
    """A definition by path and symbol, and the digest of its normalised
    body: what pairs a renamed definition with the one it was."""

    path: str
    symbol: str
    digest: str


@dataclass(frozen=True, slots=True)
class FinishedCheck:
    """One check a run finished: whether it ran, its findings and what it
    could not cover, and for a judged check the questions it put to the
    judge, its passes and its abstentions. A bounded run reports each as it
    finishes -- a check with questions only once the judge has answered
    them, so an unanswered one never reads as a pass."""

    check: Check
    findings: tuple[Finding, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    ran: bool = True
    questions: tuple[Ask, ...] = ()
    passes: tuple[Pass, ...] = ()
    abstentions: tuple[Abstention, ...] = ()


@dataclass(frozen=True, slots=True)
class RunCoverage:
    """What a run could not cover outside any one check -- a path it could
    not read, a language no analyzer measures, an analyzer that timed out.
    A bounded run reports it before its checks, so a run ended after it
    still names it."""

    coverage: tuple[Coverage, ...]


@dataclass(frozen=True, slots=True)
class Recorded:
    """Whether a report was kept, and, when it was not, the notice the
    presenter shows beside the report."""

    kept: bool
    notice: Notice | None = None


class Verdict(enum.Enum):
    """A change's verdict: not run, lowered, inconclusive, raised, or held,
    read in that order (DESIGN.ARCH-ADHERENCE.md, Judging a change)."""

    NOT_RUN = "not run"
    LOWERED = "lowered"
    INCONCLUSIVE = "inconclusive"
    RAISED = "raised"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class Report:
    """One run's outcome: the checks that ran, every finding each produced,
    the notices and the coverage, the judged checks' passes, each with its
    confidence, and their abstentions, which are neither a finding nor a
    pass, and the units the run read, each with the layer it is in, and
    each definition's body digest. A run the suite could not perform is
    not run and carries the reason; it holds nothing else, so it never
    reads as a pass.

    For a change, the report is the head's, with the verdict and why, each
    finding's provenance, and the base findings the change removed."""

    ran: tuple[Check, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[Notice, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    not_run_reason: str | None = None
    abstentions: tuple[Abstention, ...] = ()
    passes: tuple[Pass, ...] = ()
    units: tuple[Unit, ...] = ()
    verdict: Verdict | None = None
    reasons: tuple[str, ...] = ()
    removed: tuple[Finding, ...] = ()
    bodies: tuple[BodyDigest, ...] = ()
    identity: ReportIdentity | None = None
    repository: str | None = None
    revision: str | None = None

    def ran_in(self, quality: Quality) -> tuple[Check, ...]:
        """The checks of one quality that ran, in catalog order."""
        return tuple(c for c in self.ran if c.quality is quality)

    def findings_of(self, quality: Quality) -> tuple[Finding, ...]:
        """Every finding the checks of one quality produced."""
        return tuple(f for f in self.findings if f.check.quality is quality)

    @classmethod
    def not_run(cls, reason: str) -> Report:
        """The Report of a run that could not be performed, naming why."""
        return cls(not_run_reason=reason)


# --- Pure helpers ------------------------------------------------------------


def _canonical(value: object) -> object:
    """A value as plain data with one spelling: a dataclass by its fields,
    a mapping and a set in sorted order, an enum by its value."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _canonical(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return _canonical(value.value)
    if isinstance(value, Mapping):
        pairs = [[_canonical(k), _canonical(v)] for k, v in value.items()]
        return sorted(pairs, key=lambda pair: json.dumps(pair, sort_keys=True))
    if isinstance(value, set | frozenset):
        items = [_canonical(v) for v in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, tuple | list):
        return [_canonical(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"no canonical form for {type(value).__name__}")


def body_digest(text: str) -> str:
    """The digest of a body with its whitespace collapsed, so a re-indent or
    a moved definition keeps it."""
    return hashlib.sha256(normalised(text).encode("utf-8")).hexdigest()


def fingerprint(value: object) -> str:
    """A digest of a value that is the same on every machine and run."""
    text = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unfinished_checks(finished: tuple[FinishedCheck, ...]) -> tuple[Check, ...]:
    """The catalog's checks a run ended before: every one not finished, and
    the change-level checks, which finish only once the change is compared."""
    done = {f.check for f in finished}
    return tuple(c for c in CATALOG if c.quality is Quality.DECLARED or c not in done)


def assemble_partial(
    finished: tuple[FinishedCheck, ...],
    unfinished: tuple[Check, ...],
    *,
    coverage: tuple[Coverage, ...] = (),
    reason: str = ENDED,
) -> Report:
    """The Report of a run ended at the deadline: the run's own coverage,
    the finished checks as they finished, with their passes and
    abstentions, every unfinished one as coverage, and the verdict
    inconclusive -- the change was never
    compared, so it is never held or raised, and what did not finish never
    reads as a pass. `reason` is why the unfinished checks did not
    finish."""
    kept = tuple(f for f in finished if f.check not in unfinished)
    return Report(
        ran=tuple(f.check for f in kept if f.ran),
        findings=tuple(finding for f in kept for finding in f.findings),
        coverage=(
            *coverage,
            *(c for f in kept for c in f.coverage),
            *(Coverage(reason, check=c.name) for c in unfinished),
        ),
        abstentions=tuple(a for f in kept for a in f.abstentions),
        passes=tuple(p for f in kept for p in f.passes),
        verdict=Verdict.INCONCLUSIVE,
        reasons=tuple(f"{c.name}: {reason}" for c in unfinished),
    )
