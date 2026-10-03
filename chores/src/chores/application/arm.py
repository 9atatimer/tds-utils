"""Arming a run for later, and cancelling an arming (CHORES-ONE-TIME.DESIGN.md).

An arming is a run record with status ARMED. It starts nothing: the tick
fires it at its start time through normal admission, and the runner adopts
its run id. Cancelling is a check-and-set from ARMED, so it can never touch a
run that has already started.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from chores.application.context import (
    armed_record,
    binding_errors,
    end_arming,
    find_chore,
    load_context,
    mint_run_id,
)
from chores.application.run import RunDeps
from chores.domain.chore import Chore
from chores.domain.run import RunRecord, RunStatus

if TYPE_CHECKING:  # deps imports tick, which imports this module
    from chores.application.deps import Deps


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    run_id: str | None
    message: str


# --- use cases ---------------------------------------------------------------


def arm_chore(
    name: str, start_at: datetime | None, deps: RunDeps, *, armed_by: str
) -> ArmOutcome:
    """Write an ARMED record for ``name`` to start at ``start_at`` (UTC), or
    now when ``start_at`` is None.

    Refused, writing nothing, when the chore is unknown or invalid, when it
    is already armed (the message names that run), or when ``start_at`` is
    in the past. "Now" is this function's own clock read, so it can never be
    past: a caller-side read would be, once a second boundary falls between
    the two (the clock is whole seconds)."""
    ctx = load_context(deps.definitions, deps.catalog_for)
    if ctx.definitions.config_error is not None:
        return ArmOutcome(None, f"refused: {ctx.definitions.config_error}")
    found = find_chore(ctx.definitions, name)
    if found is None:
        return ArmOutcome(None, f"no chore named {name!r}")
    if not isinstance(found, Chore):
        return ArmOutcome(None, f"{name} is invalid: {found.error}")
    errors = binding_errors(ctx, found, forbidden=deps.paths.forbidden_for_cwd())
    if errors:
        return ArmOutcome(None, f"{name} is invalid: {'; '.join(errors)}")
    now = deps.clock.now_utc()
    if start_at is None:
        start_at = now
    if start_at < now:
        return ArmOutcome(
            None, f"{name}: start time {start_at.isoformat()} is in the past"
        )
    with deps.store.chore_lock(name):
        existing = armed_record(deps.store, name)
        if existing is not None:
            return ArmOutcome(None, f"{name} is already armed as {existing.run_id}")
        record = RunRecord.armed(
            run_id=mint_run_id(name, deps.clock, deps.run_id_suffix),
            chore=name,
            kind=found.kind,
            definition_rev=ctx.definitions.revision,
            start_at=start_at,
            armed_at=now,
            armed_by=armed_by,
        )
        deps.store.write_record(record)
    return ArmOutcome(record.run_id, f"{name}: armed as {record.run_id}")


def cancel_armed(run_id: str, deps: Deps) -> bool:
    """An ARMED record becomes CANCELLED; anything else is refused (False)."""
    record = deps.store.read_record(run_id)
    if record is None or record.status is not RunStatus.ARMED:
        return False
    ended = end_arming(
        deps.store,
        record,
        RunStatus.CANCELLED,
        at=deps.clock.now_utc(),
        reason="cancelled by the operator",
    )
    return ended is not None
