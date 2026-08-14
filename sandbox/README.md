# sandbox/ -- provider sandbox provisioning wrappers

Deliberately low-velocity wrappers that give every cloud-sandbox provider
the same session-start behavior. Two shapes coexist during the Phase C
migration (#145):

- ACQUIRE-then-CONFIGURE (the Claude surfaces, and the laptop path): the
  SessionStart hook is the per-session provisioning AUTHORITY -- it runs
  `lmde acquire` (installs/refreshes @nine-at-a-time-media/clai onto PATH,
  @nine-at-a-time-media/ast-mcp at ~/.local/bin/ast-mcp, and the
  @nine-at-a-time-media/skills DATA package symlinked at
  ~/.local/lib/node_modules/@nine-at-a-time-media/skills, from GitHub
  Packages; fast no-op when current) and THEN the OFFLINE, configure-only
  `clai provision`. The env-setup stage runs the same acquire but is only
  the CACHE SEEDER: its work is frozen into the environment snapshot for
  up to ~7 days, so nothing it installs is the source of truth
  (SANDBOX-LIFECYCLE.DESIGN.md). Executable pins come from the FLEET
  pins.env shipped inside the skills payload (D1: explicit --pins > fleet
  pins > float; skills itself floats by design, per
  LMDE.DESIGN.md section 2.5).
- BOOTSTRAP-and-FETCH (codex, copilot, jules -- not yet migrated): the shared
  `provision.sh` core installs a PINNED clai from GitHub Packages
  (`npm install @nine-at-a-time-media/clai@${CLAI_VERSION}`), then execs
  `clai provision`.

All behavioral churn lives inside clai, behind the pin. See
`docs/design/PROVISION.DESIGN.md` (issue #84) for the full design;
`.claude/hooks/session-start.sh` is the npm-from-Packages / fail-open
precedent these generalize.

## Layout

- `provision.sh` -- shared core for the not-yet-migrated providers (codex,
  copilot, jules); superseded for the Claude surfaces by `lmde acquire` +
  `clai provision` (see the header note in that file)
- `pins.env` -- CLAI_VERSION + AST_MCP_VERSION + SKILLS_VERSION; consumed
  by `provision.sh` for the not-yet-migrated providers. For acquire
  surfaces the pins now ride the skills
  package (template-tools packages/skills/pins.env -- see
  SANDBOX-LIFECYCLE.DESIGN.md D1 and the rollout note below)
- `codex/`, `copilot/`, `jules/` -- per-provider wrappers over `provision.sh`

`claude-web/` is GONE (#126). Its three wrappers were duplicate
implementations of what `@nine-at-a-time-media/sandbox` now ships --
`lib/setup-core.sh`, the package's own `setup-shim.sh`, and the
`naatm-sandbox-session-start` bin -- and the session-start wrapper had
DIVERGED: it provisioned its cwd only, the exact defect template-tools#417
fixed in the packaged bin (which provisions the cwd when it is a checkout,
else every immediate child checkout). Claude surfaces are served by the
package; this repo's `.claude/hooks/session-start.sh` calls the packaged bin
directly.

## Providers

| Provider | Hook contract | Install location (manual) | Network assumptions |
|----------|---------------|---------------------------|---------------------|
| Codex cloud (setup) | Setup script runs once at container create, in the repo checkout | Codex web -> Environments -> setup script: `bash sandbox/codex/setup.sh` | ON -- the only guaranteed-egress phase; full bootstrap happens here |
| Codex cloud (resume) | Maintenance script runs on cached container resume | Codex web -> Environments -> maintenance script: `bash sandbox/codex/maintenance.sh` | MAYBE OFF -- runs `provision.sh --offline-ok`; cached state + staleness warning |
| Claude Code web/remote | Env Setup script runs ONCE per snapshot-cache build (~7 days) -- the cache seeder, NOT per session. SessionStart hooks run EVERY session but NOT before `.mcp.json` loads: the client starts the MCP connect ~600 ms BEFORE the hook process spawns and finishes it ~7 s before the hook returns (measured 2026-08-14, #225), so the SEED -- not the hook -- is what makes ast-mcp answer on first connect (RD4). `CLAUDE_PROJECT_DIR` set, `CLAUDE_CODE_REMOTE=true`, hook stdout added to session context. User-scope `~/.claude/settings.json` hooks written into the container by the setup stage DO fire in cloud (#124, corrected 2026-08-13) and are the PRIMARY carrier -- also the only carrier covering multi-repo sessions, where the project dir is the checkouts' parent and repo-committed hooks never register | Env Setup script: paste `packages/naatm-sandbox/setup-shim.sh` from template-tools (installs `@nine-at-a-time-media/sandbox` and runs `naatm-sandbox setup`), which seed-acquires the fleet AND registers the user-scope SessionStart hook at `~/.claude/hooks/naatm-session-start.sh`. Repos additionally commit `.claude/hooks/session-start.sh` (templated from template-base) as REDUNDANCY -- same idempotent engine, harmless double-fire | ON in-session: `GH_AI_TOOLS_PAT` env var + npm.pkg.github.com reachable (measured 2026-08-13), so the SessionStart acquire is live; every path degrades fail-open offline. Brokered GH_TOKEN cannot read GitHub Packages -- needs the classic `read:packages` `GH_AI_TOOLS_PAT` |
| Copilot coding agent | Job named exactly `copilot-setup-steps` in `.github/workflows/copilot-setup-steps.yml`, run before the agent starts | Copy `sandbox/copilot/copilot-setup-steps.yml` to `.github/workflows/` in the target repo; add `GH_AI_TOOLS_PAT` secret | ON during setup steps; job workspace starts EMPTY (Copilot clones for the agent only after setup steps), so the workflow performs its own `actions/checkout` |
| Jules | Per-repo environment setup script, runs in the VM before the agent | Jules repo configuration -> setup script: `bash sandbox/jules/setup.sh`; add `GH_AI_TOOLS_PAT` secret | ON at setup; no separate cached-resume hook surface |

Wrappers are installed into these provider hook locations MANUALLY by the
human, one provider at a time -- automating per-repo installation of
provider hooks is an explicit design non-goal. No OSS project abstracts
over provider-hosted sandbox setup contracts (surveyed 2026-07:
OpenSandbox, E2B, sandbox-agent et al. are self-hosted runtimes, a
different problem), so the per-provider nail gets hammered by hand.

## pins.env rollout note

For ACQUIRE surfaces the rollout lever has MOVED: the fleet pins live in
template-tools `packages/skills/pins.env`, ship inside the published skills
payload, and reach every surface on its next session via the same floating
acquire that delivers the skills (SANDBOX-LIFECYCLE.DESIGN.md D1). A pin
bump is a reviewed template-tools PR; the merge is the rollout. This
repo's `pins.env` remains the lever ONLY for the not-yet-migrated
bootstrap-and-fetch providers below.

`pins.env` here: `provision.sh` sources it and `lmde
acquire --pins` reads it, so shipping new provisioning behavior to those
providers is
ONE reviewed change -- the pin bump is the review gate (same supply-chain
stance as the ast-mcp hook and ai-tools issue #72: a push to a source
repo's default branch must never grant code execution in consumers).

The pins are live. To bump them:

- Set `CLAI_VERSION` to a published `@nine-at-a-time-media/clai` version on
  GitHub Packages (`npm view @nine-at-a-time-media/clai version
  --registry=https://npm.pkg.github.com`, with a classic read:packages
  token configured, reports the latest). Land the bump via PR -- that
  review IS the gate. Delivery is npm from GitHub Packages (RD1); the old
  `CLAI_SHA256` wheel-digest pin is retired in favor of npm registry
  integrity + immutable published versions (RD3).
- Set `AST_MCP_VERSION` the same way for `@nine-at-a-time-media/ast-mcp`
  (`lmde acquire` installs it at `~/.local/bin/ast-mcp`). An UNSET key floats
  that package to registry latest.
- Leave `SKILLS_VERSION` UNSET: the skills DATA package floats by design
  (fresh sessions get current skills; the review gate is the template-tools
  PR that merged the skill edit). Pin it only to freeze a bad skill publish.
- Session hook scripts ship inside the pinned clai package (installed by
  `clai hooks install`), so they roll out via the same `CLAI_VERSION`
  bump -- there is no separate hooks pin.

If `CLAI_VERSION` is ever reset to `UNSET`, `provision.sh` fails
LOUDLY-but-open: it logs the exact fill-in procedure and exits 0 so
sessions still start. Supply-chain integrity is npm's registry check
(every downloaded tarball verified against the published integrity hash)
plus the pinned, immutable version; the session is always fail-OPEN (every
terminal state exits 0).

Skills + the MCP catalog are floating inert data again: per
LMDE.DESIGN.md (section 2, and History for why) they ship as the standalone
`@nine-at-a-time-media/skills` package, auto-published by template-tools CI
on merge, acquired floating by default (`SKILLS_VERSION` UNSET). A skill or
catalog edit reaches sandboxes on the merge that lands it; the review gate
is that PR. The clai wheel's `_data` copy (the #145 model this reverses)
survives only as clai's bootstrap fallback for unacquired surfaces.
