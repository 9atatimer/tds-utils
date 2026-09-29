"""Ceiling, breaker, admission and redaction policies (CHORES.DESIGN.md Subsystem 5)."""

from __future__ import annotations

from chores.domain.budget import Budget, Ceiling, Usage
from chores.domain.chore import BackendSpec, Chore, ExecutionPort
from chores.domain.kinds import Kind
from chores.domain.policies import (
    AdmissionFacts,
    Decision,
    LedgerUsage,
    admission_policy,
    ceiling_policy,
    circuit_breaker,
    held,
    redact,
)
from chores.domain.run import Billing, RunRecord, RunStatus

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


def test_json_escaped_redaction_form_matches_the_json_encoder() -> None:
    """The escaped form must be exactly what ``json.dumps`` (ensure_ascii) emits,
    or a secret with a control, non-ASCII or astral character persists."""
    import json

    from hypothesis import given, settings
    from hypothesis import strategies as st

    from chores.domain.policies import redact, redaction_forms

    @settings(max_examples=200, deadline=None)
    @given(st.text(min_size=1))
    def check(secret: str) -> None:
        assert json.dumps(secret)[1:-1] in redaction_forms(secret)

    check()
    for secret in ("päss\bw\f", "\U0001f512key", 'a"b\\c/d'):
        encoded = json.dumps({"k": secret})
        assert secret not in redact(encoded, [secret])
        assert json.dumps(secret)[1:-1] not in redact(encoded, [secret])


def test_a_killed_run_neither_fails_nor_resets_the_streak() -> None:
    """An operator kill says nothing about the chore, exactly as OFFLINE does
    not: it must not count as a failure, and it must not reset the count. A
    chore that hangs on every run and is killed every time still trips the
    breaker (issue #296)."""
    killed_between = [
        RunStatus.FAILED,
        RunStatus.KILLED,
        RunStatus.FAILED,
        RunStatus.KILLED,
        RunStatus.FAILED,
    ]
    assert circuit_breaker(killed_between, threshold=3).decision is Decision.PAUSE
    assert (
        circuit_breaker([RunStatus.KILLED] * 5, threshold=3).decision is Decision.KEEP
    )
    assert (
        circuit_breaker(
            [RunStatus.FAILED, RunStatus.KILLED, RunStatus.SUCCEEDED], threshold=1
        ).decision
        is Decision.KEEP
    )


def test_a_zero_threshold_breaker_pauses_nothing() -> None:
    """`all([])` is vacuously true, so an unguarded zero threshold pauses on a
    clean history. Unreachable through config.yaml, which rejects it -- the
    pure function defends itself (issue #296)."""
    assert circuit_breaker([RunStatus.SUCCEEDED], threshold=0).decision is Decision.KEEP
    assert circuit_breaker([], threshold=0).decision is Decision.KEEP


def test_ceiling_admits_spend_that_lands_exactly_on_the_cap() -> None:
    """The design refuses what would *cross* a ceiling, so equality is admitted
    -- the boundary the two neighbouring tests straddle without touching."""
    v = ceiling_policy(
        [row(usd=0.40)],
        chore=chore(usd=0.10),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert v.decision is Decision.ADMIT
    over = ceiling_policy(
        [row(usd=0.4001)],
        chore=chore(usd=0.10),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert over.decision is Decision.REFUSE


def test_a_disabled_chore_cannot_be_forced() -> None:
    """force lifts overlap, offline and battery only; disabled is not on that
    list, and the ordering is what enforces it."""
    facts = AdmissionFacts(
        enabled=False,
        globally_paused=None,
        chore_paused=None,
        running_run_id=None,
        on_battery=False,
        defer_on_battery=False,
        offline=False,
        requires_network=False,
        ceiling_refusal=None,
        force=True,
    )
    verdict = admission_policy(facts)
    assert verdict.decision is Decision.SKIP and verdict.reason == "disabled"


def test_an_unfinished_run_holds_its_declared_budget_against_the_ceilings() -> None:
    """Given a PENDING record that carries the budget it was admitted with,
    Then it holds that budget on its backend; once RUNNING it still does
    (issue #283)."""
    from datetime import datetime

    at = datetime(2026, 3, 2, 10, 0)
    pending = RunRecord.pending(
        run_id="d-1",
        chore="d",  # another chore: only the backend ceiling is shared
        kind=Kind.PROMPT,
        definition_rev="r",
        started=at,
        budget=Budget(seconds=60, tokens=1000, usd=0.4),
        backend="gw",
        billing=Billing.METERED,
    )
    h = held(pending, ledgered=False)
    assert h is not None
    assert (h.chore, h.backend, h.billing) == ("d", "gw", Billing.METERED)
    assert (h.usage.tokens, h.usage.usd, h.usage.turns) == (1000, 0.4, None)
    running = pending.start(pid=1, pgid=1, process_start=0.0)
    assert held(running, ledgered=False) == h
    verdict = ceiling_policy(
        [h, h],
        chore=chore(usd=0.3, tokens=10),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert verdict.decision is Decision.REFUSE and "backend usd" in (
        verdict.reason or ""
    )


def test_a_finished_run_holds_its_usage_until_its_ledger_row_lands() -> None:
    """The terminal record and its ledger row are two writes. Between them
    (or after a crash between them) the run holds its recorded usage, not
    its budget; once the row exists the row speaks for it."""
    from datetime import datetime

    at = datetime(2026, 3, 2, 10, 0)
    done = (
        RunRecord.pending(
            run_id="d-1",
            chore="d",
            kind=Kind.PROMPT,
            definition_rev="r",
            started=at,
            budget=Budget(seconds=60, tokens=1000, usd=0.4),
            backend="gw",
            billing=Billing.METERED,
        )
        .start(pid=1, pgid=1, process_start=0.0)
        .with_usage(Usage(tokens_in=7, tokens_out=3, seconds=1.0, usd=0.02))
        .finish(RunStatus.SUCCEEDED, ended=at, reason=None)
    )
    h = held(done, ledgered=False)
    assert h is not None and (h.usage.tokens, h.usage.usd) == (10, 0.02)
    assert h.backend == "gw"
    assert held(done, ledgered=True) is None


def test_a_command_run_holds_nothing() -> None:
    """Command chores are exempt from ceilings, so a budget one declares
    must never count against an LLM chore's admission."""
    from datetime import datetime

    pending = RunRecord.pending(
        run_id="t-1",
        chore="t",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=datetime(2026, 3, 2, 10, 0),
        budget=Budget(seconds=60, usd=0.9),
    )
    assert held(pending, ledgered=False) is None


def _unbounded(kind: Kind, billing: Billing | None, **budget: float) -> LedgerUsage:
    from chores.domain.policies import reservation

    return reservation(
        "d",
        Budget(seconds=60, **budget),  # type: ignore[arg-type]
        backend="gw",
        billing=billing,
        kind=kind,
    )


def test_an_in_flight_run_with_no_bound_in_a_capped_dimension_blocks() -> None:
    """Given a run admitted before a USD ceiling existed, so its budget sets
    no USD bound, When another chore is admitted under that ceiling, Then it
    is refused: the in-flight run's USD spend is unknown, not zero."""
    verdict = ceiling_policy(
        [_unbounded(Kind.PROMPT, Billing.METERED, tokens=100)],
        chore=chore(usd=0.1, tokens=10),
        backend=BACKEND,
        global_ceiling=Ceiling(),
        count_subscription_usd=False,
    )
    assert verdict.decision is Decision.REFUSE
    assert "no usd bound" in (verdict.reason or "")


def test_an_unbounded_dimension_that_cannot_be_spent_does_not_block() -> None:
    """The accept side: a prompt run has no turns, and a subscription run's
    USD does not count when subscription USD is not counted, so neither
    blocks admission when it leaves that dimension unbounded."""
    turns_capped = BackendSpec(
        name="gw",
        port=ExecutionPort.COMPLETION,
        default_model="m",
        requires_network=True,
        priced=True,
        ceiling=Ceiling(turns=10),
        read_only_tools=frozenset(),
    )
    prompt = _unbounded(Kind.PROMPT, Billing.METERED, tokens=100, usd=0.1)
    assert (
        ceiling_policy(
            [prompt],
            chore=chore(usd=0.1, tokens=10),
            backend=turns_capped,
            global_ceiling=Ceiling(),
            count_subscription_usd=False,
        ).decision
        is Decision.ADMIT
    )
    subscription = _unbounded(Kind.AGENT, Billing.SUBSCRIPTION, tokens=100, turns=3)
    assert (
        ceiling_policy(
            [subscription],
            chore=chore(usd=0.1, tokens=10),
            backend=BACKEND,
            global_ceiling=Ceiling(),
            count_subscription_usd=False,
        ).decision
        is Decision.ADMIT
    )
