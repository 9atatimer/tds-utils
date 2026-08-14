# Sandbox Lifecycle -- Session-Boundary Provisioning

> **Status:** DRAFT (Approach A adopted in discussion with Todd, 2026-08-13)
> **Correction (2026-08-13, post-Phase-4 verification):** fact 3 and D3 are
> corrected in place below -- a user-scope SessionStart hook WRITTEN INTO THE
> CONTAINER by the setup stage DOES fire in cloud (measured on every session
> start in a live container's harness diag logs), and it is the one carrier
> that also covers multi-repo sessions. #124's original "NO" conflated
> settings SYNC (user-level settings are not synced to cloud) with settings
> LOADING (a file present in the container loads normally).
> **Date:** 2026-08-13
> **Authors:** Claude (from design discussion with Todd)
> **Depends on:** [LMDE.DESIGN.md](./LMDE.DESIGN.md),
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
3. **Hook scopes in cloud (CORRECTED).** Cloud sessions run hooks from the
   repository (`.claude/settings.json`), from server-managed settings, AND
   from a user-scope `~/.claude/settings.json` that the setup stage wrote
   into the container. The docs' "user-level settings stay on your machine"
   describes sync, not loading: nothing copies the laptop's user settings
   into the cloud, but a settings file already present in the container
   loads like any other. Measured: the clai-0.6.0-registered user-scope
   hook fired on EVERY session start in a live container's harness diag
   logs (2.0-3.1s, exit 0) and in the Phase 4 verification session. The
   earlier "does NOT fire" conclusion here inferred non-execution from an
   absent `~/.cache/clai` -- wrong, because `clai provision --offline-ok`
   no-ops as `not_a_project` from a multi-repo parent dir without creating
   it. This answers tds-utils#124: YES, when the container writes the file.
   Corollary: repo-committed hooks do NOT register in MULTI-REPO sessions
   (the project dir is the checkouts' parent, not a repo) -- measured as
   zero provisioning in the Phase 4 verification -- so the user-scope hook
   is the one carrier that covers every session shape.
4. **In-session network + credential.** `GH_AI_TOOLS_PAT` (environment
   variable config) is present in the session environment, and
   npm.pkg.github.com answers 200 authed from inside the session. The
   RD4-era assumption that only the setup stage can reach GitHub Packages
   no longer holds.
5. **Session PATH.** `~/.local/bin` is on the session PATH (measured), so
   binaries acquired there resolve without any shell-rc edit.
6. **Multi-repo sessions.** A session opened on several checkouts has its
   project dir at the PARENT directory (e.g. `/home/user`), which is not a
   repo; repo-committed SessionStart hooks (the primary checkout's AND the
   added directories') did not load there -- zero provisioning, measured in
   the Phase 4 verification. The user-scope carrier (fact 3, corrected) is
   what covers this shape.

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
| environment setup script  |    | SessionStart hook (user-scope,    |
|   = CACHE SEEDER          |    |   setup-registered; repo-committed|
|                           |    |   shims as redundancy)            |
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

The acquire/configure axis (LMDE.DESIGN.md, section 2) is untouched:
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
  `clai hooks install` call is REMOVED -- superseded, not no-op (the
  original "proven no-op" rationale is reversed by the corrected fact 3):
  the setup stage now registers its OWN user-scope hook pointing at
  naatm-sandbox-session-start instead (D3, corrected; naatm-sandbox
  0.6.0).
- a new `naatm-sandbox-session-start` bin: the per-session authority for
  repos that are not tds-utils -- `acquire_run` then `clai provision`,
  fail-open, summary on stdout. The committed per-repo shim calls it.

Rejected: publishing acquire as its own package (a fourth moving part for
two consumers), and npm-dependency reuse (naatm-sandbox must work before
any npm install has happened).

### D3 (CORRECTED). The setup-registered user-scope hook is the primary carrier

The corrected fact 3 reverses the original D3: the user-scope carrier
EXISTS (the setup stage writes it into the container, and it fires every
session), and it is the only carrier that also covers multi-repo sessions,
where repo-committed hooks never register. So:

- PRIMARY: `naatm-sandbox setup` persists this package's bins into
  `~/.local` (the pasted Setup box runs via npx, whose cache path is not a
  stable contract), writes the managed hook script to
  `~/.claude/hooks/naatm-session-start.sh`, and merges a SessionStart
  entry into user-scope `~/.claude/settings.json` (idempotent; preserves
  unrelated keys; refuses symlinks and invalid JSON). The hook runs the
  find-engine / clai-fallback / loud-no-op ladder.
- REDUNDANCY: the repo-committed `.claude/settings.json` + shim (templated
  in template-base, and tds-utils' own committed hook) stays. In
  single-repo sessions both carriers fire; the engine is an idempotent
  fast no-op, so double-fire costs one skipped acquire pass. The committed
  shim also serves laptops and any environment whose setup stage never ran
  this package.
- The original D3's "shim provisions all sibling checkouts" fallback is
  NOT subsumed by the carrier alone -- measured in the Phase 4
  re-verification (template-tools#417): the user-scope hook fires
  regardless of project-dir shape, but `clai provision` targets its CWD
  ONLY, so from a multi-repo parent dir it no-opd as `not_a_project` and
  provisioned nothing. The discovery therefore lives in the ENGINE
  (naatm-sandbox 0.7.0): `naatm-sandbox-session-start` provisions the cwd
  when it is itself a checkout, else every immediate child checkout, else
  loudly nothing -- one provision run per checkout, per-target fail-open,
  outcomes named in the stdout summary.

---

## Sandbox reflow

```
BEFORE (RD4-era, measured broken)
  cache build   naatm-sandbox setup: pinned clai 0.6.0 + ast-mcp 0.3.2,
                user-scope hook registration (fires, but 0.6.0's hook
                no-ops outside a single-repo project dir), no skills pkg
  session       nothing runs (multi-repo: no hook; single-repo tds-utils:
                offline clai provision against the frozen snapshot)

AFTER (Approach A, carriers per D3 corrected)
  cache build   naatm-sandbox setup: acquire_run (skills float + fleet-
                pinned executables), register ast-mcp, global CLAUDE.md,
                persist self + register the user-scope session hook
  session       user-scope hook (all session shapes; repo-committed shims
                fire too in single-repo sessions -- idempotent, harmless)
                -> acquire_run (refresh to current)
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
| Session carrier (CORRECTED) | Setup-registered USER-SCOPE hook primary; committed repo shims redundancy | User-scope hooks written by setup DO fire (#124 corrected: YES) and cover multi-repo sessions, which repo hooks measurably do not |
| User-scope hook registration (CORRECTED) | Restored in the setup stage, pointing at naatm-sandbox-session-start | The original removal acted on the wrong #124 answer; the carrier works and is the multi-repo fix |
| Approach B | Future Consideration only | Elegant but swaps a solved rail for spawn-time registry coupling; its win over A is only the N-1 window |

---

## Open Questions

1. ~~Added-directory hooks.~~ ANSWERED by the Phase 4 verification: no --
   a multi-repo session's project dir is the checkouts' parent, and no
   repo-committed hook registered (zero provisioning observed). The
   user-scope carrier (D3, corrected) covers that shape.
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
- ~~User-scope SessionStart hooks as the carrier -- "measured: they do not
  fire in cloud (#124)".~~ REVERSED by the Phase 4 measurement: they do
  fire when written into the container, and are now the primary carrier
  (D3, corrected).
- **A second acquire package.** Vendoring beats a new published moving
  part for two consumers.
- **npx-spawned MCP servers now (Approach B).** Deferred: new failure
  modes (registry reachability at spawn, cold-spawn latency, npmrc-
  before-connect ordering) for a window A already shrinks to one session.

## Related Documents

- [LMDE.DESIGN.md](./LMDE.DESIGN.md) -- what acquire IS (section 2); this
  document owns when it runs.
- [PROVISION.DESIGN.md](./PROVISION.DESIGN.md) -- RD8 (cache semantics
  supersede RD4's stage assumptions).
- [LMDE.md](../../lmde/LMDE.md) -- the acquire capability this schedules.
- `sandbox/README.md` -- the wrapper tree this reflows.
- tds-utils#190, #124, #120, #123, #139, #193, #194;
  template-tools#355, #381, #382 -- the observed failure class.
