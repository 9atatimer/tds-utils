# One-Time Chores

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-03  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

Waiting fifteen minutes for a schedule to come round is too long when I
want to see whether the herd works. I am impatient, and I need a better
way to kick the tires.

A chore does not have to recur. I can define a one-time chore that only
ever runs when someone asks for it. When I ask, it either starts right
away or starts at a time I give it.

And the smoketest uses exactly that: it triggers a few smoketest one-time
chores, so kicking the tires is one command and a short wait, not a wait
for cron.

## Story sets

| File | Theme |
|---|---|
| STORIES.kicking.md | finding out, quickly, whether the herd works |

## Notes

**Settled in session (Todd's words, 2026-10-03):**

- It is possible to define one-time chores, which only run manually.
- A one-time chore can be given a start time, or start immediately.
- The smoketest triggers some smoketest one-time chores to kick the tires.
  "The smoketest" is THE smoketest: the LMDE/CLAI behavioural smoketest,
  `test/smoketest_lmde_clai/` (Todd, 2026-10-03).
- Carry it through concept, design, architecture, behaviours and
  implementation.

**Still open (nobody's yet):**

- The smoketest also runs in a cloud session, which has no chores herd;
  whether the chores probes are laptop-only there, as some of its checks
  already are.
- Whether "start time" means a one-time chore waits for the tick to reach
  it, or is started some other way, and what happens if the laptop is
  asleep at that time.
- Whether a one-time chore runs once ever, or once each time it is asked.
- Whether it spends under the same ceilings, budgets and breaker as every
  other chore.

**Leans on, existing:** `chores run <name>`, which already runs any chore
immediately through admission; the chores design (`CHORES.DESIGN.md`,
APPROVED), where every chore has a cron schedule; the two smoke chores in
the private definitions root.
