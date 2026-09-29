"""The guarding policies (CHORES.DESIGN.md Subsystem 5): ceiling, breaker,
admission and redaction. Each is a pure function with one input tuple and
one enum-carrying verdict; ``spend_policy`` and ``due_policy`` live beside
their values in ``budget`` and ``schedule``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from chores.domain.budget import Budget, Ceiling, Usage
from chores.domain.chore import BackendSpec, Chore
from chores.domain.kinds import Kind
from chores.domain.run import Billing, RunRecord, RunStatus


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
    unbounded: frozenset[str] = frozenset()
    """Dimensions an in-flight run can spend in but set no bound on (a run
    admitted before a ceiling capped that dimension): its spend there is
    unknown, not zero."""


@dataclass(frozen=True, slots=True)
class CeilingVerdict:
    decision: Decision
    reason: str | None = None


def _spendable(kind: Kind, billing: Billing | None) -> frozenset[str]:
    """The dimensions a ceiling-bound run can spend in: tokens always, USD
    unless its backend is free, turns only for an agent run."""
    out = {"tokens"}
    if billing is not Billing.NONE:
        out.add("usd")
    if kind is Kind.AGENT:
        out.add("turns")
    return frozenset(out)


def reservation(
    chore: str,
    budget: Budget,
    *,
    backend: str | None,
    billing: Billing | None,
    kind: Kind,
) -> LedgerUsage:
    """An admitted run's declared budget as a ledger row: what it holds
    against the ceilings until its real row lands (issue #283). A dimension
    the run can spend in but whose budget sets no bound is ``unbounded``:
    tokens for every ceiling-bound run, USD unless its backend is free,
    turns for an agent run."""
    return LedgerUsage(
        chore=chore,
        backend=backend,
        billing=billing,
        unbounded=_spendable(kind, billing) - budget.declared_dimensions(),
        usage=Usage(
            tokens_in=budget.tokens or 0,
            tokens_out=0,
            seconds=0.0,
            usd=None if billing is Billing.NONE else budget.usd,
            turns=budget.turns,
        ),
    )


def held(record: RunRecord, *, ledgered: bool) -> LedgerUsage | None:
    """What one record holds against the ceilings beyond the ledger rows.

    A PENDING or RUNNING run holds its declared budget (issue #283). A
    finished run whose ledger row has not landed holds its recorded usage:
    the terminal write and the row are two writes, and an admission (or a
    crash) can fall between them. A command run holds nothing -- commands
    are exempt from ceilings -- and so does everything else.
    """
    if record.kind is Kind.COMMAND:
        return None
    if not record.status.is_terminal:
        if record.budget is None:
            # Written before records carried a budget (the upgrade window):
            # its spend is unknown in every dimension it can spend in.
            return LedgerUsage(
                chore=record.chore,
                backend=record.backend,
                billing=record.billing,
                usage=Usage(tokens_in=0, tokens_out=0, seconds=0.0),
                unbounded=_spendable(record.kind, record.billing),
            )
        return reservation(
            record.chore,
            record.budget,
            backend=record.backend,
            billing=record.billing,
            kind=record.kind,
        )
    if ledgered or record.usage is None:
        return None
    return LedgerUsage(
        chore=record.chore,
        backend=record.backend,
        billing=record.billing,
        usage=record.usage,
    )


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
                # a held run on an unknown backend could be on this one
                [
                    r
                    for r in rows
                    if r.backend == backend.name or (r.backend is None and r.unbounded)
                ],
            ),
        )
    for scope, ceiling, scoped in scopes:
        for dimension in sorted(ceiling.dimensions()):
            cap = float(getattr(ceiling, dimension))
            blind = next(
                (
                    r
                    for r in scoped
                    if dimension in r.unbounded
                    and not (
                        dimension == "usd"
                        and r.billing is Billing.SUBSCRIPTION
                        and not count_subscription_usd
                    )
                ),
                None,
            )
            if blind is not None:
                return CeilingVerdict(
                    Decision.REFUSE,
                    f"{scope} {dimension} ceiling {cap:g}: {blind.chore} is in "
                    f"flight with no {dimension} bound",
                )
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
        return BreakerVerdict(Decision.PAUSE, breaker_reason(threshold))
    return BreakerVerdict(Decision.KEEP)


def breaker_reason(threshold: int) -> str:
    """The pause reason the breaker writes: how a breaker pause is told apart
    from an operator's `chores pause`."""
    return f"{threshold} consecutive failures"


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
