# Sandbox Lifecycle -- Session-Boundary Provisioning

> **Status:** DRAFT (Approach A adopted in discussion with Todd, 2026-08-13)
> **Date:** 2026-08-13
> **Authors:** Claude (from design discussion with Todd)
> **Depends on:** [LMDE-CLAI-BOUNDARY.DESIGN.md](./LMDE-CLAI-BOUNDARY.DESIGN.md),
> [PROVISION.DESIGN.md](./PROVISION.DESIGN.md),
> [LMDE.md](../../lmde/LMDE.md)

---

## Overview

The cloud sandbox provisioning model assumed the environment setup script
runs per session. It does not: it runs once per environment CACHE BUILD,
and every later session boots from a filesystem snapshot for up to ~7 days.
Everything acquired at setup time -- clai, ast-mcp, the skills package, the
pins themselves -- is therefore frozen for the cache window, which
structurally breaks Revision 1's core requirement (fresh sessions start
with current skills, no human step beyond the merge) and violates the #72
stance against stale cached binaries.

This design recasts the lifecycle around the cache boundary: the setup
script is demoted to a CACHE SEEDER, and the SessionStart hook -- which
runs every session, with network and the PAT available -- becomes the
authoritative per-session `lmde acquire && clai provision`. This is
"Approach A". "Approach B" (MCP servers acquired at spawn time via npx)
is recorded as a Future Consideration only.

---

## The measured lifecycle

All of this is measured (live cloud session, 2026-08-13) or documented at
code.claude.com ("Configure cloud environments", "Hooks reference"); none
of it is assumption.

1. **Setup script cadence.** The environment setup script runs the first
   time a session starts in an environment. Anthropic then snapshots the
   filesystem; later sessions boot from the snapshot and SKIP the setup
   script until (a) the script text changes, (b) the environment's allowed
   network hosts change, or (c) the cache expires after roughly seven
   days. Resuming a session never re-runs it.
2. **SessionStart cadence.** SessionStart hooks run at the start of EVERY
   session, startup and resume, local and cloud, after Claude Code
   launches. A hook's stdout is added to the session context.
3. **Hook scopes in cloud.** Cloud sessions run hooks from the REPOSITORY
   (`.claude/settings.json`) and from server-managed settings only.
   User-scope `~/.claude/settings.json` hooks do NOT fire -- even when the
   setup stage wrote them into the container. Measured corroboration:
   clai 0.6.0's `hooks install --scope user` registered a SessionStart
   hook at setup; it never ran (`~/.cache/clai` absent in-session). This
   answers tds-utils#124: NO.
4. **In-session network + credential.** `GH_AI_TOOLS_PAT` (environment
   variable config) is present in the session environment, and
   npm.pkg.github.com answers 200 authed from inside the session. The
   RD4-era assumption that only the setup stage can reach GitHub Packages
   no longer holds.
5. **Session PATH.** `~/.local/bin` is on the session PATH (measured), so
   binaries acquired there resolve without any shell-rc edit.
6. **Multi-repo sessions.** A session opened on several checkouts has its
   project dir at the PARENT directory (e.g. `/home/user`), which is not a
   repo; a repo-committed SessionStart hook did not load there and nothing
   provisioned. (Whether added-directory `.claude/settings.json` hooks
   fire is unmeasured -- see Open Questions.)

### What the old model got wrong

PROVISION.DESIGN.md RD4 and the sandbox/README stage table treat
"env-setup runs pre-session" as "runs per session". Consequences, all
observed:

- A skill merged today reaches cloud sessions only when the cache happens
  to rebuild -- up to ~7 days later (template-tools#355, #381, #382;
  tds-utils#190, #194).
- The pins are frozen in the snapshot too: a `pins.env` bump does nothing
  until cache expiry.
- PROVISION.DESIGN.md explicitly rejected "cached env-setup-script
  delivery of binaries" (a stale cached binary can serve a known-bad build
  with no force-refresh). The snapshot cache IS that, for the cache
  window.

---

## Goals

1. **Per-session freshness for data.** A skill merged to template-tools
   reaches the NEXT session on every surface, with no cache rebuild and no
   human step beyond the merge (Revision 1's requirement, now actually
   achievable).
2. **Per-session pin authority.** A pin bump reaches the next session, not
   the next cache rebuild. MCP-server BINARIES accept an N-1 window: the
   refreshed binary applies on the next spawn, because first connect races
   the SessionStart hook (RD4's race analysis still holds).
3. **Seed is never truth.** Everything the setup script installs is a
   warm-start optimization; the session must converge to current state
   without it (first-ever session aside, where the seed also wins the MCP
   connect race).
4. **One pins source.** The fleet pins live in exactly one reviewed place,
   readable per-session by repo-agnostic sessions (D1 below). The
   tds-utils/naatm-sandbox pins fork is closed.
5. **Drift is visible in-session.** The SessionStart hook surfaces the
   running versions and any staleness/fallback warnings into the session
   context (template-tools#381's done criteria).
6. **Fail-open everywhere, unchanged.** No provisioning failure ever
   blocks a session.

## Non-Goals

- **Approach B now.** Spawn-time acquisition of MCP servers (npx-command
  MCP entries) is a Future Consideration, not part of this design.
- **Zero-staleness MCP binaries.** The N-1 window is accepted; closing it
  is exactly Approach B.
- **Automating provider hook installation.** Still manual, still a
  design non-goal.
- **Updating running sessions.** Unchanged: running sessions are frozen;
  `clai refresh` remains the opt-in mid-session path.
- **Codex/Jules/Copilot migration.** The same seed/authority split maps
  onto them (their setup scripts have analogous caching), but this design
  only records the mapping; migration is tds-utils#139.

---

## Architecture: seed vs. authority

```
   CACHE BUILD (rare)                     EVERY SESSION
+---------------------------+    +----------------------------------+
| environment setup script  |    | SessionStart hook (repo-committed |
|   = CACHE SEEDER          |    |   or server-managed)              |
|                           |    |   = PROVISIONING AUTHORITY        |
| naatm-sandbox setup:      |    |                                   |
|   acquire run (all pkgs)  |    |  1. lmde acquire   (refresh all   |
|   register ast-mcp        |    |     packages to current pins;     |
|   place global CLAUDE.md  |    |     fast no-op when current)      |
|                           |    |  2. clai provision (configure:    |
| result -> SNAPSHOT        |    |     place skills, emit dialects)  |
|   (stale within ~7 days;  |    |  3. print version/drift summary   |
|    wins the MCP connect   |    |     to stdout -> session context  |
|    race for session 1+N)  |    |                                   |
+---------------------------+    +----------------------------------+
        NEVER the source                 ALWAYS the source
        of truth                         of truth
```

The acquire/configure axis (LMDE-CLAI-BOUNDARY.DESIGN.md) is untouched:
acquire is still agent-agnostic and owns transport/pins/integrity;
configure is still agent-aware and offline. What moves is WHEN acquire
runs: at the session boundary, not (only) the cache boundary.

The RD4 race is handled by the seed: the snapshot always contains a
working ast-mcp binary at `~/.local/bin/ast-mcp`, so first connect finds
one. The SessionStart acquire refreshes it for subsequent spawns. Stale
window: one session after a pin bump, versus up to seven days before.

---

## Decisions

### D1. The fleet pins ride the skills data package

The pins file must be readable per-session by ANY repo's session,
including repos that carry none of our files. The skills package
(`@nine-at-a-time-media/skills`) is already the one artifact every
surface acquires floating on every run, and its publish gate is a PR into
template-tools' protected main -- merge IS rollout, which is exactly the
review-gate property pins need.

- `packages/skills/pins.env` is committed in template-tools and ships in
  the published payload. A pin bump is a reviewed PR there; CI publishes
  on merge; the next session's acquire picks it up.
- `lmde acquire` resolution order, per package: explicit `--pins <file>`
  argument > fleet pins from the acquired skills package (at
  `~/.local/lib/node_modules/@nine-at-a-time-media/skills/pins.env`) >
  float to registry latest.
- The skills row itself is processed FIRST and never takes its version
  from the fleet pins of the payload being installed (self-reference): an
  emergency skills freeze uses an explicit `--pins` file or takes effect
  on the run after the frozen payload lands. Loud either way.
- `tds-utils/sandbox/pins.env` remains ONLY for the unmigrated
  bootstrap-and-fetch providers (codex/jules/copilot, #139) and is marked
  superseded for everything else. `naatm-sandbox/lib/pins.env` demotes to
  the seed's bootstrap fallback (used only before the first skills payload
  is on disk).

### D2. naatm-sandbox ships the acquire engine for repo-agnostic surfaces

`lmde acquire` lives in tds-utils, which repo-agnostic sessions do not
have. The engine (`lmde/lib/acquire.sh`) is VENDORED into
`packages/naatm-sandbox/lib/acquire.sh` -- the same deliberate-copy
mechanism as the vendored session-start hook, kept in sync by hand, drift
caught by the smoketests on both sides. bin/lmde remains the laptop and
tds-utils surface over the canonical copy.

naatm-sandbox exposes the engine twice:

- setup stage (`setup-core.sh`): one `acquire_run` (seeds every package,
  fleet pins from the just-installed skills payload) + ast-mcp user-scope
  registration + global CLAUDE.md placement. The user-scope
  `clai hooks install` call is REMOVED (proven no-op in cloud, fact 3).
- a new `naatm-sandbox-session-start` bin: the per-session authority for
  repos that are not tds-utils -- `acquire_run` then `clai provision`,
  fail-open, summary on stdout. The committed per-repo shim calls it.

Rejected: publishing acquire as its own package (a fourth moving part for
two consumers), and npm-dependency reuse (naatm-sandbox must work before
any npm install has happened).

### D3. The per-repo committed hook is accepted; multi-repo needs measurement

Fact 3 closes the door #124 hoped for: there is no user-scope carrier in
cloud, so each repo commits one small, stable `.claude/settings.json`
SessionStart entry plus a shim script. template-base carries the template
so new repos get it at cut time; existing repos adopt it by hand. The
shim is deliberately low-velocity: find the engine
(`naatm-sandbox-session-start`, else `clai provision`, else no-op), run
it fail-open. All behavioral churn stays behind the acquired packages.

Multi-repo sessions: whether added-directory repos' hooks fire is
unmeasured (Open Question 1). Until measured, the shim defensively
provisions ALL sibling checkouts it can see: `clai provision` already
walks the project dir it is given, and the shim passes the parent
directory's checkouts when the project dir is not itself a repo.

---

## Sandbox reflow

```
BEFORE (RD4-era, measured broken)
  cache build   naatm-sandbox setup: pinned clai 0.6.0 + ast-mcp 0.3.2,
                user-scope hook registration (never fires), no skills pkg
  session       nothing runs (multi-repo: no hook; single-repo tds-utils:
                offline clai provision against the frozen snapshot)

AFTER (Approach A)
  cache build   naatm-sandbox setup: acquire_run (skills float + fleet-
                pinned executables), register ast-mcp, global CLAUDE.md
  session       repo-committed hook -> acquire_run (refresh to current)
                -> clai provision (place skills, emit dialects)
                -> stdout summary into session context
```

Provider mapping (for #139, not executed here): Codex `setup.sh` is the
seeder and `maintenance.sh` approximates the session boundary; Copilot's
`copilot-setup-steps.yml` runs per-job (no cache, seed==authority); Jules
has setup only, so the committed hook is its session boundary too.

---

## Security considerations

- The supply-chain rails are unchanged: GitHub Packages only, npm
  registry integrity always on, pinned versions for executables, no
  curl|sh, ephemeral mode-600 npmrc, PAT never on disk.
- Moving acquire in-session does not widen the trust domain: the session
  already holds `GH_AI_TOOLS_PAT` in its environment.
- The snapshot cache still serves stale binaries to the FIRST spawn of a
  session (the N-1 window). This is a bounded, warned exception to the
  #72 fresh-fetch stance, chosen over Approach B's spawn-time registry
  coupling; the drift summary names the running versions every session.
- Fleet pins in the skills payload are inert data gating executable
  VERSIONS; the executables themselves still come pinned+verified from
  the registry. A tampered pins file cannot inject code that is not a
  published, integrity-checked package version.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Stage semantics | Setup = cache seeder; SessionStart = provisioning authority | Matches the platform's measured cache/hook cadence, not the assumed one |
| Freshness split | Data + configs current every session; MCP binaries N-1 | SessionStart cannot win the first-connect race (RD4); one session beats seven days |
| Pins home | `packages/skills/pins.env`, shipped in the skills payload | Merge-is-rollout review gate; reachable per-session by any repo; closes the two-pins fork |
| Pins resolution | explicit --pins > fleet pins > float | Explicit stays the emergency override; float stays the no-config default |
| Engine for repo-agnostic surfaces | Vendored acquire.sh in naatm-sandbox + `naatm-sandbox-session-start` bin | Works with zero repo files; same deliberate-vendoring precedent as the hook |
| Per-repo carrier | Committed `.claude/settings.json` + shim, templated in template-base | User-scope hooks measurably do not fire in cloud (#124: NO) |
| User-scope hook registration | Removed from the setup stage | Proven no-op; dead weight and a false sense of coverage |
| Approach B | Future Consideration only | Elegant but swaps a solved rail for spawn-time registry coupling; its win over A is only the N-1 window |

---

## Open Questions

1. **Added-directory hooks.** Does a multi-repo cloud session run
   SessionStart hooks from added directories' `.claude/settings.json`?
   Measure in the Phase 4 verification session; the shim's
   provision-all-siblings behavior covers the gap either way.
2. **Seed staleness floor.** Should the seeder deliberately skip
   executables entirely (empty-ish setup script) once Approach B lands
   for MCP servers? Revisit with B.
3. **Unpublished packages.** git-mirror and sandbox-qol resolve
   UNREADABLE on the registry (2026-08-13) -- their pins gate nothing
   today. Publish or drop from the rails (tds-utils#188, #192 adjacent).

## Rejections

- **Keep acquire at setup, shorten the cache.** The cache lifetime is not
  ours to configure; forcing rebuilds by touching the script is a manual
  step, which is the failure class Revision 1 exists to kill.
- **User-scope SessionStart hooks as the carrier.** Measured: they do not
  fire in cloud (#124).
- **A second acquire package.** Vendoring beats a new published moving
  part for two consumers.
- **npx-spawned MCP servers now (Approach B).** Deferred: new failure
  modes (registry reachability at spawn, cold-spawn latency, npmrc-
  before-connect ordering) for a window A already shrinks to one session.

## Related Documents

- [LMDE-CLAI-BOUNDARY.DESIGN.md](./LMDE-CLAI-BOUNDARY.DESIGN.md) --
  Revision 2 (acquire timing moves to the session boundary).
- [PROVISION.DESIGN.md](./PROVISION.DESIGN.md) -- RD8 (cache semantics
  supersede RD4's stage assumptions).
- [LMDE.md](../../lmde/LMDE.md) -- the acquire capability this schedules.
- `sandbox/README.md` -- the wrapper tree this reflows.
- tds-utils#190, #124, #120, #123, #139, #193, #194;
  template-tools#355, #381, #382 -- the observed failure class.
