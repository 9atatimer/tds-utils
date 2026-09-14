"""Ceiling, breaker, admission and redaction policies (CHORES.DESIGN.md Subsystem 5)."""

from __future__ import annotations

from chores.domain.budget import Ceiling, Usage
from chores.domain.chore import BackendSpec, Chore, ExecutionPort
from chores.domain.policies import (
    AdmissionFacts,
    Decision,
    LedgerUsage,
    admission_policy,
    ceiling_policy,
    circuit_breaker,
    redact,
)
from chores.domain.run import Billing, RunStatus

BACKEND = BackendSpec(
    name="gw",
    port=ExecutionPort.COMPLETION,
    default_model="m",
    requires_network=True,
    priced=True,
    ceiling=Ceiling(usd=1.0, tokens=100_000),
    read_only_tools=frozenset(),
)


def chore(**budget: float) -> Chore:
    return Chore.from_mapping(
        {
            "name": "c",
            "schedule": "* * * * *",
            "kind": "prompt",
            "backend": "gw",
            "budget": budget or {"usd": 0.10, "tokens": 1000},
            "ceiling": {"usd": 0.5},
        },
        body="x",
    )


def row(
    *,
    chore_name: str = "c",
    backend: str = "gw",
    usd: float,
    tokens: int = 0,
    billing: Billing = Billing.METERED,
) -> LedgerUsage:
    return LedgerUsage(
        chore=chore_name,
        backend=backend,
        billing=billing,
        usage=Usage(tokens_in=tokens, tokens_out=0, usd=usd, seconds=1),
    )


# --- ceiling -----------------------------------------------------------------


def test_ceiling_admits_when_spent_plus_declared_fits() -> None:
    """Given 0.30 spent, a 0.50 chore ceiling and a 0.10 budget, Then ADMIT."""
    v = ceiling_policy(
        [row(usd=0.30)],
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.ADMIT


def test_ceiling_refuses_when_declared_budget_would_cross_chore_ceiling() -> None:
    """Given 0.45 spent, a 0.50 chore ceiling and a 0.10 budget, Then REFUSE (chore)."""
    v = ceiling_policy(
        [row(usd=0.45)],
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.REFUSE and "chore" in (v.reason or "")


def test_backend_ceiling_counts_other_chores_on_that_backend() -> None:
    """Given others spent 0.95 on gw (ceiling 1.00) and a 0.10 budget, Then REFUSE."""
    v = ceiling_policy(
        [row(chore_name="other", usd=0.95)],
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.REFUSE and "backend" in (v.reason or "")


def test_global_ceiling_counts_every_row() -> None:
    """Given 9,500 tokens spent, a 10,000 global cap and a 1000 budget, Then REFUSE."""
    rows = [
        row(chore_name="a", backend="x", usd=0.0, tokens=5000),
        row(chore_name="b", backend="y", usd=0.0, tokens=4500),
    ]
    v = ceiling_policy(
        rows,
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(tokens=10_000),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.REFUSE and "global" in (v.reason or "")


def test_subscription_usd_excluded_by_default_but_tokens_count() -> None:
    """Given 0.99 subscription USD on gw, Then USD is excluded but tokens count."""
    rows = [row(usd=0.99, tokens=99_500, billing=Billing.SUBSCRIPTION)]
    v = ceiling_policy(
        rows,
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.REFUSE and "tokens" in (v.reason or "")
    v2 = ceiling_policy(
        [row(usd=0.99, billing=Billing.SUBSCRIPTION)],
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v2.decision is Decision.ADMIT
    v3 = ceiling_policy(
        [row(usd=0.99, billing=Billing.SUBSCRIPTION)],
        chore=chore(),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=True,
    )
    assert v3.decision is Decision.REFUSE


# --- breaker -----------------------------------------------------------------


def test_breaker_pauses_after_threshold_consecutive_failures() -> None:
    """Given three straight failures (threshold 3), Then PAUSE; a success keeps."""
    fails = [RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.BUDGET_EXCEEDED]
    assert circuit_breaker(fails, threshold=3).decision is Decision.PAUSE
    assert (
        circuit_breaker(
            [RunStatus.FAILED, RunStatus.SUCCEEDED, RunStatus.FAILED], threshold=3
        ).decision
        is Decision.KEEP
    )
    assert circuit_breaker(fails[:2], threshold=3).decision is Decision.KEEP


def test_breaker_ignores_skips_and_offline() -> None:
    """Given OFFLINE and SKIPPED between failures, Then the streak is unbroken."""
    seq = [
        RunStatus.FAILED,
        RunStatus.OFFLINE,
        RunStatus.SKIPPED_OVERLAP,
        RunStatus.FAILED,
        RunStatus.FAILED,
    ]
    assert circuit_breaker(seq, threshold=3).decision is Decision.PAUSE


# --- admission ---------------------------------------------------------------


def facts(**over: object) -> AdmissionFacts:
    base: dict[str, object] = dict(
        enabled=True,
        globally_paused=None,
        chore_paused=None,
        running_run_id=None,
        on_battery=False,
        defer_on_battery=False,
        offline=False,
        requires_network=True,
        ceiling_refusal=None,
        force=False,
    )
    base.update(over)
    return AdmissionFacts(**base)  # type: ignore[arg-type]


def test_admits_when_nothing_objects() -> None:
    assert admission_policy(facts()).decision is Decision.ADMIT


def test_global_pause_wins_over_everything_and_force() -> None:
    """Given PAUSED with a reason, even forced, Then SKIPPED_PAUSED with that reason."""
    v = admission_policy(facts(globally_paused="flight", force=True))
    assert v.record_status is RunStatus.SKIPPED_PAUSED and "flight" in (v.reason or "")


def test_breaker_pause_and_ceiling_are_not_forceable() -> None:
    assert (
        admission_policy(facts(chore_paused="breaker", force=True)).record_status
        is RunStatus.SKIPPED_PAUSED
    )
    assert (
        admission_policy(facts(ceiling_refusal="backend usd", force=True)).record_status
        is RunStatus.SKIPPED_CEILING
    )


def test_overlap_offline_battery_are_forceable() -> None:
    assert (
        admission_policy(facts(running_run_id="c-1")).record_status
        is RunStatus.SKIPPED_OVERLAP
    )
    assert (
        admission_policy(facts(running_run_id="c-1", force=True)).decision
        is Decision.ADMIT
    )
    assert (
        admission_policy(facts(offline=True)).record_status is RunStatus.SKIPPED_OFFLINE
    )
    assert (
        admission_policy(facts(offline=True, requires_network=False)).decision
        is Decision.ADMIT
    )
    assert (
        admission_policy(facts(on_battery=True, defer_on_battery=True)).record_status
        is RunStatus.DEFERRED_BATTERY
    )
    assert (
        admission_policy(
            facts(on_battery=True, defer_on_battery=True, force=True)
        ).decision
        is Decision.ADMIT
    )
    assert admission_policy(facts(on_battery=True)).decision is Decision.ADMIT


def test_disabled_chore_writes_no_record() -> None:
    v = admission_policy(facts(enabled=False))
    assert v.decision is Decision.SKIP and v.record_status is None


# --- redaction ---------------------------------------------------------------


def test_redact_covers_verbatim_json_escaped_and_url_encoded_forms() -> None:
    """Given a secret with quotes and slashes, Then all three forms are replaced."""
    secret = 'to/ken"1'
    escaped = 'to/ken\\"1'
    encoded = "to%2Fken%221"
    text = f"raw {secret} json {escaped} url {encoded} end"
    out = redact(text, [secret])
    assert secret not in out and escaped not in out and encoded not in out
    assert out.count("[REDACTED]") == 3


def test_redact_with_no_secrets_is_identity() -> None:
    assert redact("plain", []) == "plain"
    assert redact("plain", [""]) == "plain"
