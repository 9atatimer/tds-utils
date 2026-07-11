# Universal Agent Provisioning (clai provision)

> **Status:** DRAFT  
> **Superseded/split 2026-07-11 (step two):** the acquire half of this unified
> design moved to `lmde acquire`; the configure half narrowed to an offline
> `clai provision`. See
> [LMDE-CLAI-BOUNDARY.DESIGN.md](./LMDE-CLAI-BOUNDARY.DESIGN.md) (authoritative
> for the boundary) and
> [template-tools#145](https://github.com/nine-at-a-time-media/template-tools/issues/145)
> (the bundling mechanism). Kept for history.  
> **Date:** 2026-07-03  
> **Authors:** Claude (from issue #84 and design discussion with Todd)  
> **Depends on:** [CLAI.DESIGN.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md), [issue #84](https://github.com/9atatimer/tds-utils/issues/84)

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

> **Superseded / folded (step two, 2026-07-11).** This unified design has been
> split on the acquire/configure axis; the reconciled model now lives in the
> canonical docs. In brief:
>
> - **Acquisition** (install clai + ast-mcp, pins, supply-chain integrity) is
>   now `lmde acquire`, installing two GitHub-Packages npm packages
>   (`@nine-at-a-time-media/clai`, `@nine-at-a-time-media/ast-mcp`).
> - **`clai provision` is configure-only and fully offline.** `GitSourceFetcher`
>   is deleted; skills + catalog are bundled in the clai wheel (`clai/_data`)
>   per template-tools#145 and materialized offline into
>   `~/.cache/clai/template-tools/`.
> - The currency machine keeps its shape but its identity flips from
>   `remote_head` (git sha) to `local_stamp` (content digest of the bundled
>   `_data`).
> - Accepted consequence: skills stop floating on a bare `template-tools` push;
>   a skill rollout is a clai release + `CLAI_VERSION` bump in
>   `sandbox/pins.env` (the review gate).
>
> See [LMDE-CLAI-BOUNDARY.DESIGN.md](./LMDE-CLAI-BOUNDARY.DESIGN.md) (authoritative)
> and [LMDE.md](../../lmde/LMDE.md). The rest of this document is kept for
> history; where it describes a git-over-proxy data pull at provision time, that
> is superseded by the offline-materialization model above.

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
6. **Supply-chain discipline** -- Every *executable* artifact (clai, hook
   scripts) is version-pinned and integrity-verified before use (npm
   registry integrity for GitHub Packages, RD3). Only inert data (skills,
   manifest) floats to latest.

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
| template-tools releases      |    |    -> bootstrap clai wheel       |
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
    Register session hooks per agent, on the surface each agent
    actually has (as implemented):
      claude: SessionStart registration in .claude/settings.json plus
        a managed hook script (embedded in the clai package).
      codex / agy / opencode: no native session-hook surface exists,
        so a clai.d/<agent>/pre/05-provision overlay hook is installed
        instead -- it fires only when the agent is launched through
        clai. Native registration (codex config.toml, ~/.gemini
        config, opencode.json) is future work if those agents grow a
        startup-hook surface.
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
| Session hook scripts | Embedded in the clai package (`clai hooks install`); `template-tools/hooks/` is the source the embedded templates are synced from | Ship inside the pinned clai package; roll out by bumping `CLAI_VERSION` (no separate hooks pin) |
| clai | `@nine-at-a-time-media/clai` on **GitHub Packages** (npm) | Pinned version; npm registry integrity (see "Revised Decisions") |

> **Revised 2026-07 (#98/#99/#101):** clai (formerly a wheel) and ast-mcp are
> no longer delivered as **GitHub Release assets fetched over `api.github.com`**
> -- that path is blocked by the Claude web agent proxy. Both now ship via
> **GitHub Packages** (`npm.pkg.github.com`), which is reachable. See the
> "Revised Decisions" section for the transport, token, and verification
> changes this forces. The rows above are kept but read them through that lens.

One repo (`template-tools`) is the provisioning pull for all inert data
(skills, manifest), so a provision run needs one fetch for that. Executables
(clai, ast-mcp) come from **GitHub Packages**, not a git checkout or release
download. `template-tools` data access uses `gh` / git-over-proxy when
present; **GitHub Packages reads require a classic `read:packages` token**
(`GH_AI_TOOLS_PAT`) -- fine-grained PATs have no Packages permission (see
"Revised Decisions").

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

**Antigravity note:** As of 2026-07, agy natively supports the Agent Skills
open standard (SKILL.md with YAML frontmatter). This is confirmed by official
Google sources -- the antigravity.google/docs/skills page and the "Getting
started with Antigravity Skills" codelab (codelabs.developers.google.com) --
and corroborated by Gemini CLI's own SKILL.md support, since the two Gemini
agents share the format. No shim is required: agy discovers SKILL.md directly
from a global scope (~/.gemini/config/skills/) and a workspace scope
(<project-root>/.agents/skills/), so its emitter writes the same SKILL.md the
other agents consume rather than a knowledge-config shim. Two caveats to verify
against the target install: the exact global path varies across docs
(~/.gemini/config/skills/ vs ~/.gemini/skills/), and the IDE has a known bug
ignoring symlinked skills (vercel-labs/skills#633) -- so in ephemeral sandboxes
emit copies, not symlinks. This resolves Open Question 2.

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
    "ast-mcp":   { "command": "${CLAUDE_PROJECT_DIR:-.}/.ast-mcp/node_modules/.bin/ast-mcp", "args": [] },
    "ghl-sites": { "command": "npx", "args": ["-y", "@ghl/mcp-sites"],
                   "env": { "GHL_API_KEY": "${GHL_API_KEY}" } }
  }
}
```

> **Revised 2026-07 (#98):** the ast-mcp command was `"${AST_MCP_BIN}"`, but
> that variable is exported only by interactive shell dotfiles, which the MCP
> client process never sources -- so it expanded empty and the server never
> launched. `${VAR}` indirection in a committed MCP command only works for
> vars present in the spawned server's OWN process. Claude Code sets
> `CLAUDE_PROJECT_DIR` there and supports `${VAR:-default}`, so the
> project-relative form above is the correct one. Secrets (`${GHL_API_KEY}`)
> are still fine -- they are resolved from the agent's launch environment,
> which the server process inherits.

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
- **Two emitter target classes (#95).** The four above are *file-target*
  agents, written via the `ConfigStore` port. Copilot's coding agent is a
  fifth, *repo-settings-API-target* agent: its MCP config lives in repo
  settings, not a file. GitHub exposes
  `GET /repos/{owner}/{repo}/copilot/cloud-agent/configuration` (read-only)
  for the coding agent's `mcp_configuration` but **no write endpoint** -- the
  server list is UI-only. So clai **cannot apply** it. `emit_copilot`
  therefore renders the managed servers for manual entry and provision
  surfaces them on a loud MANUAL-ACTION warning channel; it never silently
  no-ops. Read-only pending a GitHub write endpoint (re-verify before adding
  a write adapter). The writable `COPILOT_MCP_*` Agents secrets/variables
  surface is out of manifest scope (the manifest carries no secret values).
- Today's `10-disable-cloudflare-mcp` hook becomes a `"disable"` entry.

### Sandbox wrapper tree (decision)

> **Revised 2026-07 (#101, RD1/RD3):** the original wording in this section
> ("bootstrap clai wheel, verify sha256"; `pins.env` = `CLAI_VERSION` +
> `CLAI_SHA256`) is superseded and kept only for history. `provision.sh` now
> installs clai from **GitHub Packages**
> (`npm install @nine-at-a-time-media/clai@${CLAI_VERSION}`), and `pins.env`
> carries **only `CLAI_VERSION`** -- the `CLAI_SHA256` wheel-digest pin is
> retired in favor of npm registry integrity (RD3). The tree and the
> "low-velocity wrappers" note below reflect this model; `claude-web/` also
> carries `setup.sh`, the pre-session ast-mcp installer (#99). See "Revised
> Decisions" (RD1-RD5) for the full transport/token/verification changes.

New top-level `sandbox/` in `tds-utils`:

```
sandbox/
  provision.sh              shared core: bootstrap clai (pinned), run
                            `clai provision`
  pins.env                  CLAI_VERSION -- the ONLY moving part (hook
                            scripts ship inside the clai package)
  codex/setup.sh            container create (network on): full bootstrap
  codex/maintenance.sh      cached resume (network may be off): provision
                            --offline-ok
  claude-web/setup.sh       env-setup (pre-session): install+register ast-mcp
  claude-web/session-start.sh
  copilot/copilot-setup-steps.yml
  jules/setup.sh
```

- Wrappers are deliberately **low-velocity**: npm-install the pinned clai
  version from GitHub Packages (npm verifies registry integrity), exec
  `clai provision`. All behavioral churn lives inside clai, behind the pin.
  Rolling out new provisioning behavior everywhere = editing `pins.env` (one
  reviewed change), since every wrapper sources it.
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
| START | BOOTSTRAP FAILED | pinned clai cannot be installed from GitHub Packages | cloud wrapper, no prior install |

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

- **No unpinned code execution** -- Executables are pinned to a released
  version and installed from a registry that verifies artifact integrity;
  hook scripts ship inside the pinned clai package, so they inherit the same
  gate. This preserves the stance documented in `session-start.sh` (ai-tools
  issue #72 lineage): a push to a source repo's default branch must not grant
  code execution in consumers; the version pin is the review gate.
  **Revised 2026-07 (#98):** delivery moved from GitHub Release assets +
  hand-fetched `.sha256` to **GitHub Packages** (npm), whose registry
  integrity check verifies every downloaded tarball; the pin is now a package
  version rather than a wheel sha. See "Revised Decisions."
- **Skills float but are prompt surface** -- Skills are data, not code, but
  they steer agents. Mitigations: `template-tools` is private with
  protected main; provision only ever pulls from that one repo; the
  provision report names which skills changed since last run.
- **Never curl-pipe-sh** -- Software lands only via package managers with
  registry integrity (GitHub Packages npm), never a piped script (existing
  CLAUDE.md law, restated as a provision invariant).
- **Secrets** -- Manifest layers carry `${VAR}` references only; resolution
  happens in the agent's environment at launch. Provision never writes a
  secret value into a generated config.
- **Token scoping** -- Inert-data access (`template-tools` skills/manifest via
  git) uses the brokered token / git-over-proxy. Executable delivery from
  **GitHub Packages requires a classic `read:packages` token** -- fine-grained
  PATs have no Packages permission (**Revised 2026-07 (#98)**: this replaces
  the original "fine-grained Contents:read PAT" here). `GH_AI_TOOLS_PAT` is
  that classic `read:packages` token; keep its scope minimal (packages read
  only).
- **Guarded destructive ops** -- Any `rm -rf` of managed dirs must pattern-
  check the path (ast-mcp hook precedent) before deleting.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Skill format | Open SKILL.md standard (dir per skill, frontmatter) | Adopted by all target agents in 2026; native lazy-loading replaces hand-rolled dispatch; ecosystem tooling exists |
| Code vs data update policy | Executables pinned; skills/manifest float | Matches supply-chain stance already documented in session-start.sh; skills are inert and must be fresh to be useful. **Revised 2026-07:** "checksummed release asset" -> "pinned version on GitHub Packages, registry integrity" (see Revised Decisions) |
| Artifact delivery transport | GitHub Packages npm (`npm.pkg.github.com`) | **Added 2026-07 (#98/#101):** the Claude web agent proxy blocks raw GitHub release-asset egress (`api.github.com`/`releases/download` both fail); GitHub Packages is reachable. Needs a classic `read:packages` token |
| MCP-server binary install timing | Environment SETUP step, not the SessionStart hook | **Added 2026-07 (#99):** Claude Code connects `.mcp.json` servers concurrently with the SessionStart hook; a hook that installs the binary loses the race (ENOENT on first spawn, no retry). The binary must exist before session init; the hook is a refresh/fallback |
| Update model | New sessions auto-fresh; running sessions frozen; manual `clai refresh` best-effort with report | Todd's explicit requirement; avoids surprise mid-session mutation |
| MCP config source | One canonical manifest + profile subscription + repo/user overlay layers | Kills four-dialect hand-maintenance; per-repo server sets (GHL) via one `profiles` line |
| Manifest format | JSON | `jq`-friendly for shell fallbacks; Python stdlib parseable; authored rarely, merged by machine |
| Manifest layer location | `clai.d/mcp.json` at existing walk levels | Reuses clai's proven overlay walk and closest-wins semantics; no new config surface |
| Repo skill customization | Parametric -> repo-local data file; behavioral -> project-scope shadow skill | Eliminates the manual-merge category that blocks automation; mirrors clai.d shadowing |
| Sandbox wrappers | Thin, manually installed, all pins in one `pins.env` | Providers have incompatible hook contracts and no OSS abstraction exists; low-velocity wrapper makes the pin bump the only rollout step |
| Provision engine home | clai (`template-tools`), new reserved verbs | clai is already the per-agent knowledge locus (launcher, telemetry, overlay walk) and is installed everywhere via LMDE |
| Refresh semantics | `refresh` = `provision --report` | One engine, two entry points; report is the contract with the user |
| Hook registration surface | claude: native SessionStart in `.claude/settings.json`; codex/agy/opencode: `clai.d/<agent>/pre/05-provision` overlay hook only | Provisioning recon found no native session-hook surface for codex/agy/opencode; the overlay hook covers clai-launched sessions today, native registration is future work if those agents grow one |
| Hook script delivery | Embedded in the pinned clai package (`clai hooks install`), not fetched from `template-tools` at a separate pin | The package is already pinned + integrity-checked, giving hooks the same supply-chain gate with one fewer pin to manage |

---

## Revised Decisions (2026-07, post #98 / #99 / #101)

Implementing the sandbox delivery against real Claude Code web sandboxes
surfaced facts that reverse several decisions above. The originals are kept
for history; these supersede them.

### RD1. Delivery transport: GitHub Releases -> GitHub Packages (npm)

**Finding.** The Claude web agent proxy blocks raw GitHub release-asset
egress: `GET api.github.com/.../releases` returns a synthetic 403 and
`github.com/.../releases/download/*` returns 404 -- independent of token, and
independent of session repo scope. The sanctioned, reachable channels are the
GitHub MCP server, git-over-proxy, and the **GitHub Packages npm registry**
(`npm.pkg.github.com`).

**Decision.** All executables ship via GitHub Packages and install with
`npm install`:

- ast-mcp: `@nine-at-a-time-media/ast-mcp` (native node package).
- clai / crmagic / designomatic: published as npm packages that wrap each
  tool's self-contained shiv `.pyz` (`bin` -> the pyz; `SHIV_ENTRY_POINT`
  selects alias entrypoints). GitHub Packages has no PyPI feed, so this is how
  Python artifacts ride the same rail as everything else.
- The `naatm-*` packages were already on GitHub Packages; the whole fleet now
  uses one install mechanism.

The "fetch the release `.tgz`/wheel over `api.github.com` + verify a paired
`.sha256`" model (old `fetch_tarball` / `bootstrap_clai` / `pins.env`
`CLAI_SHA256`) is retired for the sandbox path. clai's migration is tracked in
#101; ast-mcp's shipped in #98.

### RD2. Token model: fine-grained Contents:read -> classic `read:packages`

**Finding.** GitHub Packages npm reads require the **classic** `read:packages`
scope. Fine-grained PATs have no Packages permission at all and 403 with
"token does not match expected scopes."

**Decision.** `GH_AI_TOOLS_PAT` is a classic `read:packages` token, scoped as
narrowly as that allows. Executable delivery no longer needs repo Contents
access (the artifact comes from the registry, not a git checkout); inert-data
pulls of `template-tools` continue to use git-over-proxy / the brokered token.

### RD3. Verification: hand-fetched `.sha256` -> npm registry integrity + version pin

**Finding.** With registry delivery, npm verifies every downloaded tarball
against the registry-published integrity hash, and published versions on
GitHub Packages are immutable.

**Decision.** The supply-chain gate is the **pinned package version** (the
review gate) plus npm's built-in integrity check. The `#72` stance is intact
-- a default-branch push still does not grant execution in consumers, because
consumers pin a released version -- it is just enforced by the registry rather
than a wheel sha in `pins.env`.

### RD4. MCP-server binary install: SessionStart hook -> environment setup

**Finding.** Delivery being fixed was necessary but not sufficient. On a fresh
web session the ast-mcp binary installs cleanly but the server does not
connect: Claude Code attempts the `.mcp.json` connection **concurrently with**
the SessionStart hook, and the hook's `npm install` has not finished writing
the binary yet -> first spawn ENOENTs with no auto-retry -> the server is
absent until a later reconnect (observed connecting late on return to the
session). A SessionStart hook fundamentally cannot win this race for the
binary it is itself installing.

**Decision.** MCP-server binaries must be installed in the environment SETUP
step (which runs before session init, so the binary exists when MCP first
connects). The repo-committed `.mcp.json` + SessionStart hook remain, but the
hook is an idempotent refresh/fallback, not the first-connect installer. This
refines the "config must be written before the agent launches" premise:
writing the config early is necessary but not sufficient; the binary it points
at must also exist before session init. Scope choice (user `~/.claude.json` vs
project `.mcp.json`) tracked in #99.

**Resolved (#99): ONE binary path, registered at both scopes.** The env-setup
installer is `sandbox/claude-web/setup.sh` (paste as the Claude web
Environment "Setup script"). It installs `@nine-at-a-time-media/ast-mcp` via
`npm install -g --prefix "$HOME/.local"`, landing the executable at
`~/.local/bin/ast-mcp` -- the *same* path the `clai.d/*/pre/20-enable-ast-mcp`
hooks register and the *same* path the laptop's `install-claude-user.sh`
writes -- and registers it in `~/.claude.json`. The committed project
`.mcp.json` names that identical binary as `"${HOME}/.local/bin/ast-mcp"`,
which Claude Code expands in the spawned server's own environment (RD5).

Because both scopes resolve to one executable, **ast-mcp connects whichever
scope wins.** This matters, because scope resolution is not what the original
#99 write-up assumed. Measured against a live `claude mcp list`:

- Project and user scope are matched **by name**; the highest-precedence
  source supplies the *entire* entry (no field merging). Project scope
  outranks user scope.
- An **unapproved** project `.mcp.json` entry is *skipped*, and Claude falls
  back to the user-scope server. A fresh clone carries no approval (the
  approving `.claude/settings.local.json` is gitignored, and a checked-in
  `enableAllProjectMcpServers` is ignored in an untrusted folder), so in a
  cloud sandbox **user scope carries first connect**.
- An **approved** project entry shadows user scope entirely. On a laptop,
  where the human approved it once, the project entry is what runs.

The earlier design -- project entry pointing at a project-local `.ast-mcp/`
tree installed separately by setup.sh and the SessionStart hook -- therefore
had two install sites for one server, two failure modes, and a permanent
`[Conflicting scopes]` diagnostic (the two scopes named different endpoints).
It also broke the laptop outright: nothing installs `.ast-mcp/` there (the
hook is remote-gated and needs a token the laptop lacks), so the approved
project entry shadowed a perfectly good user-scope binary with a path that did
not exist. The project-local install is **removed**; the SessionStart hook is
an idempotent user-scope refresh that never deletes the env-setup copy.

Delivery/token/verification follow RD1-RD3 (GitHub Packages, classic
`read:packages`, npm integrity; ast-mcp floats to `@latest` as in #98).
Remaining proof: ast-mcp *connected on first load* requires cutting a fresh
web session after setup.sh is wired into the cloud-env config -- it cannot be
fully confirmed from within the session that writes the fix.

### RD5. Committed MCP command: only reference vars in the server's own process

**Finding.** `"command": "${AST_MCP_BIN}"` failed because `AST_MCP_BIN` is
exported only by interactive shell dotfiles, which the MCP client process
never sources -> empty expansion -> no launch.

**Decision.** A committed MCP command may only reference variables present in
the spawned server's own environment. Claude Code sets `CLAUDE_PROJECT_DIR`
there and honors `${VAR:-default}`, so project-relative paths use
`${CLAUDE_PROJECT_DIR:-.}/...`. Secret indirection (`${GHL_API_KEY}`) is
unaffected -- those come from the agent's launch environment.

**Enforced (2026-07, template-tools#144).** RD5 was recorded here but never
propagated into the canonical `mcp/manifest.json`, which kept
`"command": "${AST_MCP_BIN}"`. Since `clai provision` *regenerates*
`.mcp.json` on every run, every run silently reverted the hand-corrected
committed value back to the broken placeholder -- the design doc said one
thing and the generator wrote another. Reproduced directly:

```
${AST_MCP_BIN}              -> Failed to connect
                               [Warning] Missing environment variables: AST_MCP_BIN
${HOME}/.local/bin/ast-mcp  -> Connected
```

The manifest now names `${HOME}/.local/bin/ast-mcp`. `$HOME` is the one
variable **both** environments supply and every MCP client's child process
has, and both installers already land the binary there.

The remaining subtlety is that not every agent's client expands variables, so
clai resolves placeholders **per target** (`clai.domain.placeholders`):

| Target | Committed? | Client expands `${VAR}`? | clai emits |
|---|---|---|---|
| `<repo>/.mcp.json` (claude) | yes | yes | the placeholder, **literal** |
| `~/.codex/config.toml` | no | no | a **resolved** absolute path |
| `~/.gemini/config/mcp_config.json` (agy) | no | no | **resolved** |
| `~/.config/opencode/opencode.json` | no | no | **resolved** |

Resolving into the committed file would bake a machine-specific path into
version control and churn the diff on every provision run; leaving it literal
in the user-scope configs would never launch. Only an allowlist
(`PROVISION_VARS`, currently `{HOME}`) is ever resolved, so `${GHL_API_KEY}`
still reaches the agent as a placeholder and is never written into a config
file -- and a reintroduced `${AST_MCP_BIN}` stays literal rather than being
papered over, which is a regression test.

### RD6. Central global CLAUDE.md: delivered by the setup stage, cloud-only, create-if-absent

**Finding.** `claude.ai > Settings > General > Instructions` is NOT shared with
Claude Code (neither CLI nor web/remote), so cross-cutting, repo-agnostic agent
instructions never reach a session -- only per-repo `CLAUDE.md`/`AGENT.md` load.
There is also no public/CLI API to read or sync that claude.ai field (the web
app's save endpoint is internal, cookie-gated, unsupported).

**Decision (tds-utils#127, landed template-tools#151).** Ship a repo-agnostic
global `CLAUDE.md` as INERT DATA bundled inside `@nine-at-a-time-media/sandbox`
(`assets/CLAUDE.global.md`, in `files[]`) -- the package version stays the
single review gate, so no new pin and no second pre-session install. It rides
the same setup stage that installs ast-mcp (RD4: the only phase both
post-checkout and pre-session-init, so the file is on disk before Claude Code
loads memory). Placement contract:

- **Cloud only** (`CLAUDE_CODE_REMOTE` truthy or `HOME=/root`); a laptop/real
  checkout is a no-op.
- **Two targets, nothing else:** `/etc/claude-code/CLAUDE.md` (primary, system
  scope, outside home) -> `/root/CLAUDE.md` (fallback). `~` is NEVER mutated;
  `~/.claude` is off-limits.
- **Create-if-absent, never overwrite;** refuse a symlink/special target;
  atomic temp+`mv`, mode 644; fail-open (setup stage always `exit 0`).
- Loads hierarchically with each repo's own `CLAUDE.md` (repo wins on
  specificity), keeping global and repo instructions distinct.

Rejected `~/.claude/CLAUDE.md` (mutating home) and treating `/etc/claude-code`
as override-proof managed policy (wrong semantics -- repos must be able to
supplement). Published `@nine-at-a-time-media/sandbox@0.2.0`.

**Caveat (measured).** Claude Code ingests the placed file VERBATIM -- HTML
comments are not stripped -- so any non-instruction content (e.g. a "generated,
don't edit" header) costs tokens every session and reads as instruction-
adjacent. Keep the placed file instruction-only; put provenance out of the file
body. (See Future Considerations.)

---

## Open Questions

1. **`npx skills` as placement engine?** -- Vercel's skills CLI already
   maps skills into 27+ agents' directories. Adopting it removes our
   placement table but adds a pinned Node dependency to provision. Decide
   during implementation after testing its symlink behavior locally.
2. **Antigravity skill support** (RESOLVED 2026-07) -- agy consumes SKILL.md
   natively from `~/.gemini/config/skills/` (global) and
   `<project-root>/.agents/skills/` (workspace); no knowledge-config shim is
   needed. See the Antigravity note under "Skill format and placement."
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
  **Partially revised 2026-07 (RD4/#99):** MCP-server binaries specifically
  MUST be installed at environment-setup time, because MCP connect races the
  SessionStart hook (a session-time install isn't on disk when the server is
  first spawned). Freshness is preserved a different way: setup installs a
  pinned, registry-verified version on container create, and the SessionStart
  hook re-runs `npm install` as an idempotent refresh (applies on the next
  connect). The rejection still holds for its original target -- an *unpinned,
  never-refreshed* cached blob -- which this is not.
- **Symlinks in ephemeral sandboxes** -- The clone the links point into is
  discarded with the container; copies are the only durable form there.
- **Enforcing agent behavior by mutating global Claude Code settings (#127)** --
  A `permissions.deny` on a tool (e.g. `AskUserQuestion`) in
  `~/.claude/settings.json` would hard-block the behavior, but the owner
  rejected the sandbox touching global settings at all (risk of breaking the
  harness). The behavior is carried by the global `CLAUDE.md` instruction text
  instead; the sandbox writes exactly one thing -- the global `CLAUDE.md` -- and
  mutates nothing else global.

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
- **Strip the managed-header comment from the placed global CLAUDE.md** -- it is
  read verbatim every session (~25 tokens, instruction-adjacent; see RD6
  caveat). Move provenance to a sibling marker or the package README so the
  placed file is 100% instruction tokens. Tracked as a follow-up issue.

---

## Related Documents

- [CLAI.DESIGN.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md) -- the launcher this design adds verbs to
- [HOWTO.SYNC.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/prompts/HOWTO.SYNC.md) -- the manual sync workflow this design retires
- `.claude/hooks/session-start.sh` (this repo) -- the fetch/verify/fail-open precedent the wrappers generalize
- [LMDE-OBSERVABILITY.DESIGN.md](./LMDE-OBSERVABILITY.DESIGN.md) -- collector that would receive provision telemetry (open question 6)
