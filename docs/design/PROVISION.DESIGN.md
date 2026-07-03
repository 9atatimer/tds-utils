# Universal Agent Provisioning (clai provision)

> **Status:** DRAFT  
> **Date:** 2026-07-03  
> **Authors:** Claude (from issue #84 and design discussion with Todd)  
> **Depends on:** [CLAI.DESIGN.md](https://github.com/9atatimer/ai-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md), [issue #84](https://github.com/9atatimer/tds-utils/issues/84)

---

## Overview

Agent tooling (skills, MCP server configs, hook scripts) is currently pushed
into repos once at template-cut time and then drifts -- a fix to a skill in
`template-tools` never reaches existing repos, cloud sandboxes, or cached
sandbox resumes. This design makes every **new** session self-provision from
the canonical source at start, for every agent (Claude Code, Codex,
Antigravity/agy, OpenCode), in every environment (laptop, fresh cloud
sandbox, cached/resumed sandbox), with a manual `clai refresh` verb for
best-effort mid-session updates.

---

## Goals

1. **Skill freshness** -- Editing a skill in `template-tools` and starting a
   new session in (a) a fresh cloud sandbox, (b) a cached/resumed sandbox,
   (c) an on-laptop repo yields the updated skill for every agent, with no
   manual steps beyond the one-time per-environment hook install.
2. **One MCP manifest** -- All agents' MCP configs are generated from one
   canonical manifest plus per-repo overlays; adding a server to a profile
   appears in every subscribed repo's configs on next provision.
3. **Stale-image immunity** -- A new session in a sandbox whose image was
   cut weeks ago still starts with current skills, manifest output, and hook
   scripts (network permitting).
4. **Honest degradation** -- No network at provision time never blocks a
   session: cached state is used and a warning names exactly what is stale.
5. **Cheap idempotence** -- A provision run that finds everything current
   exits 0 in under 2 seconds (one `git ls-remote`-class check, no clone).
6. **Supply-chain discipline** -- Every *executable* artifact (clai wheel,
   hook scripts) is version-pinned and checksum-verified before use. Only
   inert data (skills, manifest) floats to latest.

---

## Non-Goals

- **Updating running sessions automatically** -- An existing session is
  frozen. Updates land only via an explicit, user-requested `clai refresh`,
  which reports what it could and could not update.
- **Live MCP hot-reload** -- Agents load MCP server sets at process start.
  `clai refresh` regenerates configs and *reports* that a restart (or new
  session) is required to load them; it does not attempt runtime injection.
- **Copilot coding agent MCP config** -- Copilot takes MCP config via repo
  settings (`gh api`), not files. Follow-up issue; skills for Copilot are in
  scope via `copilot-setup-steps.yml`.
- **Claude-only plugin marketplace distribution** -- Single-agent channel;
  the point here is agent-universal.
- **Per-repo installation of provider hooks** -- The deliverable is the
  canonical `sandbox/` tree; Todd installs wrappers into provider hook
  locations (repo settings, workflow files, environment configs) manually.

---

## Architecture Overview

```
        CANONICAL SOURCES                        ENVIRONMENTS
+------------------------------+    +----------------------------------+
| template-tools (private)     |    | Cloud sandbox (Codex / Claude    |
|   skills/<name>/SKILL.md     |    |  web / Copilot / Jules)          |
|   mcp/manifest.json          |    |                                  |
|   hooks/ (session hooks)     |    |  provider pre-agent hook         |
+------------------------------+    |    -> sandbox/ wrapper (PINNED)  |
| ai-tools releases (private)  |    |    -> bootstrap clai wheel       |
|   clai-x.y.z wheel + .sha256 |    |       (verify sha256)            |
+------------------------------+    |    -> clai provision             |
        |            |              +----------------------------------+
        | data:      | code:        | Laptop (LMDE)                    |
        | floats     | pinned +     |                                  |
        | to latest  | verified     |  clai <agent>  (alias)           |
        v            v              |    -> pre-hook -> clai provision |
+------------------------------+    |  .claude SessionStart (non-clai |
|        clai provision        |    |   launches) -> clai provision    |
|  fetch -> merge -> generate  |    +----------------------------------+
+------------------------------+
        |
        v
  per-agent outputs: skills dirs, .mcp.json / config.toml /
  mcp_config.json / opencode.json, hook registrations
```

---

## Design

### Freshness model (decision)

Three tiers, per Todd's explicit requirement:

| Tier | Trigger | Behavior |
|------|---------|----------|
| New session | Provider pre-agent hook / clai pre-hook | Full provision before the agent process starts. Everything current: skills, MCP configs, hook scripts (at their pins). |
| Existing session | (none) | Frozen. Nothing mutates a running session in the background. |
| Manual refresh | User asks the agent to run `clai refresh` | Best-effort: skills always hot-swap (inert, read lazily); hook scripts and tools update at their pins; MCP configs regenerate but need an agent restart to load. Ends with an honest report of what updated, what is staged for next start, and what it could not do. |

The user accepts the reported outcome; a new session is the remedy for
anything refresh cannot hot-swap.

### clai verbs

`clai` today is a passthrough launcher with one reserved verb (`shim`).
This design reserves three more, using the same carve-out mechanism in
`cli.py`:

```
clai provision [--report] [--offline-ok]
    Fetch canonical sources, sync skills, generate MCP configs,
    update hook scripts to their pins. Idempotent. Exit 0 fast when
    current. Never fails the session for a fetch error unless
    --offline-ok is absent AND there is no cached state at all.

clai refresh
    Alias for `clai provision --report`, intended to be run mid-session
    by the agent on user request. The report distinguishes:
      updated now (skills), staged for next agent start (MCP configs,
      hook registrations), skipped (no network / pin unchanged),
      failed (with reason).

clai hooks install [--agent <name> | --all] [--scope project|user]
    Write hook registrations into each agent's config surface
    (.claude/settings.json SessionStart; codex config.toml;
    ~/.gemini config; opencode.json) and link the hook scripts into
    each agent's expected path.
```

`provision` is the single engine; session-start wrappers and `refresh` are
entry points into it. Structure follows clai's existing hexagonal layout:
pure planning (what is stale, what to write) in `domain/`, fetch/write
adapters at the edges, per-agent emitters as a table of small pure
functions.

### Canonical sources

| Artifact | Home | Update policy |
|----------|------|---------------|
| Skills (`skills/<name>/SKILL.md`) | `template-tools` | Floats to latest on default branch (inert data) |
| MCP manifest (`mcp/manifest.json`) | `template-tools` | Floats to latest (inert data; consumed only by clai's generator) |
| Session hook scripts (`hooks/`) | `template-tools` | Pinned tag + checksum; provision updates them only when the pin moves |
| clai wheel | `ai-tools` GitHub Release | Pinned version + `.sha256` in each sandbox wrapper |

One repo (`template-tools`) is the provisioning pull for all data, so a
provision run needs exactly one fetch plus (when pins move) one release
download. `template-tools` is private; access uses `gh` when present, else
a `GH_AI_TOOLS_PAT`-class fine-grained PAT -- the exact fallback chain
already proven in `.claude/hooks/session-start.sh` (the ast-mcp installer).

### Skill format and placement (decision)

Skills adopt the open **SKILL.md standard** (directory per skill, YAML
frontmatter with `name`/`description`): supported by Claude Code, Codex
CLI, Gemini CLI, Copilot, OpenCode, Cursor, and others as of 2026. The flat
`prompts/SKILL.*.md` files in `naatm-prompts` migrate to
`skills/<name>/SKILL.md`; the existing `load_when`/`skip_when` frontmatter
folds into each skill's `description` trigger text. `SKILL.INDEX.md`'s
dispatch role is subsumed by native skill discovery; its Always-In-Effect
Laws move to the (small, stable) root agent file.

Placement per environment:

- **Laptop:** one clone under `~/.cache/clai/template-tools/`; agent skill
  dirs get **symlinks** into it, so one `git pull` refreshes every agent.
- **Ephemeral sandboxes:** **copies** (sandboxes are discarded; symlink
  sources would not survive image caching anyway).
- The per-agent destination map (which directory each agent reads) lives in
  clai's emitter table. Driving Vercel's `npx skills` CLI instead of our own
  placement map is an open question (see below) -- if adopted, it must be
  version-pinned like any other executable.

**Antigravity caveat:** agy's skill support is unverified; if it lacks
native SKILL.md support, its emitter generates entries in agy's knowledge
config from the same skill source (shim, not fork).

### Per-repo skill customization (decision)

The `<!-- Localized for org/repo -->` manual-merge model is retired. Two
replacement mechanisms:

| Kind | Example | Mechanism |
|------|---------|-----------|
| Parametric | repo owner, default branch, branch prefix, merge style | Shared skill is pure logic and instructs the agent to read a small repo-owned data file (e.g. `skills/github-workflow/LOCAL.md`) that provision never touches |
| Behavioral | a repo whose GH flow genuinely diverges | Repo commits its own skill of the same name at project scope; native skill precedence (project shadows managed/global) makes closest-win, mirroring `clai.d` overlay semantics |

Provision rules: it owns the managed skill set and overwrites it freely; it
never writes into repo-committed overlay paths; it **warns loudly** when a
managed file carries unexpected local edits (straggler detector), instead of
silently skipping like `naatm-prompts sync` does today.

### MCP manifest and layering (decision)

One canonical manifest defines every known server once; repos subscribe by
**profile**. Layer merge reuses the `clai.d` overlay walk levels:

```
canonical (template-tools mcp/manifest.json)      -- all servers, tagged
  <- repo layer   <repo>/clai.d/mcp.json          -- committed per repo
  <- user layer   ~/clai.d/mcp.json               -- machine-local quirks
(closest wins, field-level merge)
```

Canonical manifest shape (JSON: `jq`-friendly in shell, stdlib-parseable in
clai):

```
{
  "profiles": {
    "base": ["ast-mcp"],
    "ghl":  ["ghl-sites", "ghl-crm"]
  },
  "servers": {
    "ast-mcp":   { "command": "${AST_MCP_BIN}", "args": [] },
    "ghl-sites": { "command": "npx", "args": ["-y", "@ghl/mcp-sites"],
                   "env": { "GHL_API_KEY": "${GHL_API_KEY}" } }
  }
}
```

Repo layer:

```
{
  "profiles": ["base", "ghl"],
  "servers":  { "repo-only-server": { ... } },
  "disable":  ["cloudflare-graphql"]
}
```

- Secrets never appear in any layer -- `${VAR}` env indirection only.
- A GoHighLevel repo opts in with one `"profiles"` line; no other repo ever
  sees those servers.
- Generation emits each agent's dialect from the merged view: Claude
  `.mcp.json` / `~/.claude.json`, Codex `~/.codex/config.toml`
  (tomllib-probe + append/replace, per the existing hook), agy
  `~/.gemini/config/mcp_config.json`, OpenCode
  `~/.config/opencode/opencode.json`. The four hand-written
  `clai.d/*/pre/20-enable-ast-mcp` hooks are the seed code for these
  emitters and are retired once the generator lands.
- Today's `10-disable-cloudflare-mcp` hook becomes a `"disable"` entry.

### Sandbox wrapper tree (decision)

New top-level `sandbox/` in `tds-utils`:

```
sandbox/
  provision.sh              shared core: bootstrap clai (pinned), run
                            `clai provision`
  pins.env                  CLAI_VERSION, CLAI_SHA256, HOOKS_TAG,
                            HOOKS_SHA256 -- the ONLY moving part
  codex/setup.sh            container create (network on): full bootstrap
  codex/maintenance.sh      cached resume (network may be off): provision
                            --offline-ok
  claude-web/session-start.sh
  copilot/copilot-setup-steps.yml
  jules/setup.sh
```

- Wrappers are deliberately **low-velocity**: fetch pinned wheel, verify
  sha256, install, exec `clai provision`. All behavioral churn lives inside
  clai, behind the pin. Rolling out new provisioning behavior everywhere =
  editing `pins.env` (one reviewed change), since every wrapper sources it.
- Wrappers tolerate no-egress-after-setup: all fetching happens in the
  setup phase; a maintenance/resume hook that cannot reach the network uses
  cached state and emits a warning naming what is stale (Goal 4).
- Todd installs these into provider hook locations manually, one provider
  at a time. No OSS project abstracts over provider-hosted sandbox setup
  contracts (surveyed 2026-07: OpenSandbox, E2B, sandbox-agent et al. are
  self-hosted runtimes, a different problem), so the per-provider nail
  gets hammered by hand.

### Session-start hook (local coverage)

The repo-committed `.claude/hooks/session-start.sh` becomes a three-way
branch instead of remote-only:

```
if command -v clai        -> clai provision        (laptop, any entry path)
elif CLAUDE_CODE_REMOTE   -> sandbox bootstrap     (cloud, pinned)
else                      -> no-op + warning
```

This covers local Claude Code sessions launched outside the clai aliases
(desktop app, IDE extension). Agents launched via `clai <agent>` are
covered by a `clai.d/<agent>/pre/` provision hook regardless of provider
hooks. Both paths converge on the same idempotent `clai provision`, so
double-invocation is a fast no-op (Goal 5).

---

## State Machine

Provision-run outcome states:

```
+-----------+   pins/data stale,   +----------+
|  CURRENT  |<---------------------| UPDATING |
+-----------+   applied cleanly    +----------+
      ^                                 |
      | nothing stale                   | fetch fails, cache exists
      |                                 v
+-----------+                      +----------+
|   START   |--------------------->| DEGRADED |  (warn; exit 0)
+-----------+   no network,        +----------+
      |         cache exists
      | no network, NO cache
      v
+-----------+
| BOOTSTRAP |  (cloud only: cannot install clai -> log, exit 0,
|  FAILED   |   session starts without provisioning)
+-----------+
```

| From | To | Trigger | Condition |
|------|----|---------|-----------|
| START | CURRENT | currency check passes | remote heads match cached state |
| START | UPDATING | currency check finds drift | network available |
| UPDATING | CURRENT | sync + generate complete | all writes atomic (tmpfile + rename) |
| START | DEGRADED | fetch fails | cached skills/manifest exist |
| START | BOOTSTRAP FAILED | clai wheel cannot be fetched/verified | cloud wrapper, no prior install |

Every terminal state exits 0 from the session's point of view; only the
report differs. A checksum-verification failure is fail-closed for the
*artifact* (it is not installed; stale prior copy is removed, following the
ast-mcp hook precedent) but fail-open for the *session*.

---

## Data Model

No database. On-disk state:

```
~/.cache/clai/
+-- template-tools/          shallow clone (laptop) or snapshot (sandbox)
+-- provision-state.json     last-known-good: source commit, pin versions,
|                            per-agent generation hashes, timestamp
+-- wheels/                  verified clai wheels by version (sandbox)
```

`provision-state.json` is what makes the currency check cheap (compare
`git ls-remote` head + pins against recorded values) and what DEGRADED mode
reports against.

---

## Security Considerations

- **No unpinned code execution** -- Hook scripts and the clai wheel are
  fetched at a pinned tag/version and sha256-verified before install
  (fail-closed per artifact). This preserves the stance documented in
  `session-start.sh` (ai-tools issue #72 lineage): a push to a source
  repo's default branch must not grant code execution in consumers; the
  pin bump is the review gate.
- **Skills float but are prompt surface** -- Skills are data, not code, but
  they steer agents. Mitigations: `template-tools` is private with
  protected main; provision only ever pulls from that one repo; the
  provision report names which skills changed since last run.
- **Never curl-pipe-sh** -- Software lands only via package managers /
  release artifacts with checksums (existing CLAUDE.md law, restated as a
  provision invariant).
- **Secrets** -- Manifest layers carry `${VAR}` references only; resolution
  happens in the agent's environment at launch. Provision never writes a
  secret value into a generated config.
- **Token scoping** -- Sandbox access to the two private repos uses the
  brokered token where the provider supplies one, else a dedicated
  fine-grained PAT (Contents:read), mirroring the ast-mcp hook's chain.
- **Guarded destructive ops** -- Any `rm -rf` of managed dirs must pattern-
  check the path (ast-mcp hook precedent) before deleting.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Skill format | Open SKILL.md standard (dir per skill, frontmatter) | Adopted by all target agents in 2026; native lazy-loading replaces hand-rolled dispatch; ecosystem tooling exists |
| Code vs data update policy | Executables pinned + checksummed; skills/manifest float | Matches supply-chain stance already documented in session-start.sh; skills are inert and must be fresh to be useful |
| Update model | New sessions auto-fresh; running sessions frozen; manual `clai refresh` best-effort with report | Todd's explicit requirement; avoids surprise mid-session mutation |
| MCP config source | One canonical manifest + profile subscription + repo/user overlay layers | Kills four-dialect hand-maintenance; per-repo server sets (GHL) via one `profiles` line |
| Manifest format | JSON | `jq`-friendly for shell fallbacks; Python stdlib parseable; authored rarely, merged by machine |
| Manifest layer location | `clai.d/mcp.json` at existing walk levels | Reuses clai's proven overlay walk and closest-wins semantics; no new config surface |
| Repo skill customization | Parametric -> repo-local data file; behavioral -> project-scope shadow skill | Eliminates the manual-merge category that blocks automation; mirrors clai.d shadowing |
| Sandbox wrappers | Thin, manually installed, all pins in one `pins.env` | Providers have incompatible hook contracts and no OSS abstraction exists; low-velocity wrapper makes the pin bump the only rollout step |
| Provision engine home | clai (`ai-tools`), new reserved verbs | clai is already the per-agent knowledge locus (launcher, telemetry, overlay walk) and is installed everywhere via LMDE |
| Refresh semantics | `refresh` = `provision --report` | One engine, two entry points; report is the contract with the user |

---

## Open Questions

1. **`npx skills` as placement engine?** -- Vercel's skills CLI already
   maps skills into 27+ agents' directories. Adopting it removes our
   placement table but adds a pinned Node dependency to provision. Decide
   during implementation after testing its symlink behavior locally.
2. **Antigravity skill support** -- Verify whether agy consumes SKILL.md
   natively; if not, spec the knowledge-config shim.
3. **Skill-tree reconciliation** -- `tds-utils/prompts`, `ai-tools/prompts`,
   and `naatm-prompts/prompts` have all diverged (verified 2026-07-03:
   nearly every shared file differs; each side has files the other lacks).
   The migration to `template-tools/skills/` is the moment to reconcile.
   Needs a file-by-file sweep with Todd deciding winners; stragglers like
   `SKILL.TECH_RADAR.md` / `SKILL.LMDE_DASHBOARDS.md` get promoted to
   canonical or marked repo-local.
4. **naatm-prompts retirement** -- After migration, does the npm package
   remain as a legacy channel for template-base consumers, or is it
   retired in favor of provision everywhere?
5. **Codex cloud secrets** -- Confirm which secret surface Codex setup
   scripts can read for the PAT, and whether the brokered token cases
   (Claude web) cover both private repos.
6. **Provision telemetry** -- Should provision runs emit OTel metrics
   (duration, outcome state, staleness age) to the LMDE collector like
   clai launches do?

---

## Rejections

- **Fetch-and-execute unpinned scripts at session start** -- Supply-chain
  hole (default-branch push = code execution in every consumer); rejected
  previously in ai-tools issue #72 and again here; pins + checksums instead.
- **Status quo: per-agent hand-maintained MCP configs and copied prompts**
  -- The drift this design exists to kill; empirically confirmed diverged.
- **Claude plugin marketplace as distribution channel** -- Single-agent;
  does not cover Codex/agy/OpenCode.
- **devcontainer.json as the cross-provider abstraction** -- Provider
  support is partial and inconsistent; does not cover cached-resume hooks.
- **Auto-updating running sessions** -- Surprise mutation mid-session;
  explicitly unwanted; replaced by opt-in `clai refresh`.
- **Cached env-setup-script delivery of binaries** -- A stale cached binary
  can serve a known-vulnerable build for the cache window with no force-
  refresh (ai-tools issue #72); fetch-fresh-and-verify each session instead.
- **Symlinks in ephemeral sandboxes** -- The clone the links point into is
  discarded with the container; copies are the only durable form there.

---

## Future Considerations

- **Copilot coding agent MCP config** -- Requires `gh api` against repo
  settings; file as follow-up issue once the manifest schema is stable.
- **MCP hot-reload** -- If agents grow config-reload support, `clai
  refresh` can upgrade "staged for next start" to "applied".
- **Pre/post-tool universal hooks** -- The universal hook set is scoped to
  session-start sync now; the same shim pattern extends to standardized
  pre/post-tool hooks later.
- **Coordinator integration** -- clai's overlay-hook seam for TODO leasing
  (CLAI.DESIGN.md v2 notes) composes with, but is independent of, this
  design.

---

## Related Documents

- [CLAI.DESIGN.md](https://github.com/9atatimer/ai-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md) -- the launcher this design adds verbs to
- [HOWTO.SYNC.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/prompts/HOWTO.SYNC.md) -- the manual sync workflow this design retires
- `.claude/hooks/session-start.sh` (this repo) -- the fetch/verify/fail-open precedent the wrappers generalize
- [LMDE-OBSERVABILITY.DESIGN.md](./LMDE-OBSERVABILITY.DESIGN.md) -- collector that would receive provision telemetry (open question 6)
