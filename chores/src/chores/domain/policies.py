"""The guarding policies (CHORES.DESIGN.md Subsystem 5): ceiling, breaker,
admission and redaction. Each is a pure function with one input tuple and
one enum-carrying verdict; ``spend_policy`` and ``due_policy`` live beside
their values in ``budget`` and ``schedule``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from chores.domain.budget import Ceiling, Usage
from chores.domain.chore import BackendSpec, Chore
from chores.domain.kinds import Kind
from chores.domain.run import Billing, RunStatus


class Decision(Enum):
    ADMIT = "admit"
    REFUSE = "refuse"
    SKIP = "skip"
    KEEP = "keep"
    PAUSE = "pause"


# --- ceiling -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerUsage:
    """One ledger row reduced to what the ceiling policy needs."""

    chore: str
    backend: str | None
    billing: Billing | None
    usage: Usage


@dataclass(frozen=True, slots=True)
class CeilingVerdict:
    decision: Decision
    reason: str | None = None


def _spent(
    rows: Iterable[LedgerUsage], *, dimension: str, count_subscription_usd: bool
) -> float:
    total = 0.0
    for r in rows:
        if dimension == "usd":
            if r.billing is Billing.SUBSCRIPTION and not count_subscription_usd:
                continue
            total += r.usage.usd or 0.0
        elif dimension == "tokens":
            total += r.usage.tokens
        elif dimension == "turns":
            total += r.usage.turns or 0
    return total


def _declared(chore: Chore, dimension: str) -> float:
    value = getattr(chore.budget, dimension)
    return float(value) if value is not None else 0.0


def ceiling_policy(
    rows: Sequence[LedgerUsage],
    *,
    chore: Chore,
    backend: BackendSpec | None,
    global_ceiling: Ceiling,
    count_subscription_usd: bool,
) -> CeilingVerdict:
    """REFUSE when spent-in-window plus this chore's declared budget would cross
    any applicable ceiling; the smallest applicable ceiling wins. Command
    chores spend no tokens, USD or turns, so no ceiling applies to them."""
    if chore.kind is Kind.COMMAND:
        return CeilingVerdict(Decision.ADMIT)
    scopes: list[tuple[str, Ceiling, list[LedgerUsage]]] = [
        ("chore", chore.ceiling, [r for r in rows if r.chore == chore.name]),
        ("global", global_ceiling, list(rows)),
    ]
    if backend is not None:
        scopes.insert(
            1,
            (
                "backend",
                backend.ceiling,
                [r for r in rows if r.backend == backend.name],
            ),
        )
    for scope, ceiling, scoped in scopes:
        for dimension in sorted(ceiling.dimensions()):
            cap = float(getattr(ceiling, dimension))
            spent = _spent(
                scoped,
                dimension=dimension,
                count_subscription_usd=count_subscription_usd,
            )
            projected = spent + _declared(chore, dimension)
            if projected > cap:
                return CeilingVerdict(
                    Decision.REFUSE,
                    f"{scope} {dimension} ceiling {cap:g}: spent {spent:g} + "
                    f"declared {_declared(chore, dimension):g} would exceed it",
                )
    return CeilingVerdict(Decision.ADMIT)


# --- breaker -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreakerVerdict:
    decision: Decision
    reason: str | None = None


def circuit_breaker(recent: Sequence[RunStatus], *, threshold: int) -> BreakerVerdict:
    """PAUSE when the last ``threshold`` run-terminal outcomes were all failures.

    Skips, OFFLINE and KILLED are neither failures nor streak breakers: they
    say nothing about the chore itself. KILLED has to be transparent in both
    directions or the operator's own remediation defeats the breaker -- a
    chore that hangs every time and is killed every time would reset the
    streak on each kill and never pause (issue #296).
    """
    transparent = (RunStatus.OFFLINE, RunStatus.KILLED)
    considered = [s for s in recent if s.is_run_terminal and s not in transparent]
    tail = considered[-threshold:] if threshold > 0 else []
    if threshold > 0 and len(tail) == threshold and all(s.is_failure for s in tail):
        return BreakerVerdict(Decision.PAUSE, f"{threshold} consecutive failures")
    return BreakerVerdict(Decision.KEEP)


# --- admission ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmissionFacts:
    enabled: bool
    globally_paused: str | None
    chore_paused: str | None
    running_run_id: str | None
    on_battery: bool
    defer_on_battery: bool
    offline: bool
    requires_network: bool
    ceiling_refusal: str | None
    force: bool


@dataclass(frozen=True, slots=True)
class AdmissionVerdict:
    decision: Decision
    record_status: RunStatus | None = None
    reason: str | None = None


def admission_policy(f: AdmissionFacts) -> AdmissionVerdict:
    """ADMIT or SKIP with the record to write. PAUSED (global or breaker) and a
    ceiling refusal are never lifted by ``force``; overlap, offline and battery are.
    """
    if f.globally_paused is not None:
        return AdmissionVerdict(
            Decision.SKIP, RunStatus.SKIPPED_PAUSED, f"paused: {f.globally_paused}"
        )
    if f.chore_paused is not None:
        return AdmissionVerdict(
            Decision.SKIP, RunStatus.SKIPPED_PAUSED, f"chore paused: {f.chore_paused}"
        )
    if not f.enabled:
        return AdmissionVerdict(Decision.SKIP, None, "disabled")
    if f.ceiling_refusal is not None:
        return AdmissionVerdict(
            Decision.SKIP, RunStatus.SKIPPED_CEILING, f.ceiling_refusal
        )
    if f.force:
        return AdmissionVerdict(Decision.ADMIT)
    if f.running_run_id is not None:
        return AdmissionVerdict(
            Decision.SKIP,
            RunStatus.SKIPPED_OVERLAP,
            f"{f.running_run_id} still running",
        )
    if f.offline and f.requires_network:
        return AdmissionVerdict(
            Decision.SKIP, RunStatus.SKIPPED_OFFLINE, "backend unreachable"
        )
    if f.on_battery and f.defer_on_battery:
        return AdmissionVerdict(Decision.SKIP, RunStatus.DEFERRED_BATTERY, "on battery")
    return AdmissionVerdict(Decision.ADMIT)


# --- redaction ---------------------------------------------------------------

_REDACTED = "[REDACTED]"
_JSON_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}
_URL_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~")


def _json_escaped_char(ch: str) -> str:
    """One character as ``json.dumps`` (ensure_ascii, the adapters' default)
    would emit it: the short escapes, ``\\u00XX`` for other controls, and
    ``\\uXXXX`` (a surrogate pair above the BMP) for everything non-ASCII."""
    short = _JSON_ESCAPES.get(ch)
    if short is not None:
        return short
    code = ord(ch)
    if 0x20 <= code < 0x7F:
        return ch
    if code < 0x10000:
        return f"\\u{code:04x}"
    code -= 0x10000
    return f"\\u{0xD800 | (code >> 10):04x}\\u{0xDC00 | (code & 0x3FF):04x}"


def _json_escaped(value: str) -> str:
    return "".join(_json_escaped_char(ch) for ch in value)


def _url_encoded(value: str) -> str:
    return "".join(
        ch if ch in _URL_SAFE else "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
        for ch in value
    )


def redaction_forms(value: str) -> frozenset[str]:
    """The forms of one secret the redaction claim covers (Goals)."""
    return frozenset({value, _json_escaped(value), _url_encoded(value)})


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every covered form of every secret, longest form first."""
    forms = sorted(
        {form for s in secrets if s for form in redaction_forms(s)},
        key=len,
        reverse=True,
    )
    for form in forms:
        text = text.replace(form, _REDACTED)
    return text
