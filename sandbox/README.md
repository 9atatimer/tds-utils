# sandbox/ -- provider sandbox provisioning wrappers

Deliberately low-velocity wrappers that give every cloud-sandbox provider
the same session-start behavior. Two shapes coexist during the Phase C
migration (#145):

- ACQUIRE-then-CONFIGURE (claude-web, and the laptop path): a pre-session
  env-setup stage runs `lmde acquire` -- installs @nine-at-a-time-media/clai
  (onto PATH) and @nine-at-a-time-media/ast-mcp (at ~/.local/bin/ast-mcp) from
  GitHub Packages, with skills + the MCP catalog riding INSIDE the clai wheel
  -- and the SessionStart hook then runs an OFFLINE, configure-only
  `clai provision` (no clone, no install). Both packages are version-controlled
  through ONE `--pins sandbox/pins.env` file (keys CLAI_VERSION + AST_MCP_VERSION
  -- a real value pins, absent/UNSET/"latest" floats to registry latest).
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
  copilot, jules); superseded for claude-web by `lmde acquire` + `clai
  provision` (see the header note in that file)
- `pins.env` -- CLAI_VERSION + AST_MCP_VERSION; the ONLY moving part (see
  rollout note below). Both are read by `lmde acquire --pins`; CLAI_VERSION is
  also consumed by `provision.sh`
- `claude-web/` -- acquire-then-configure wrappers (`setup.sh` runs `lmde
  acquire`; `session-start.sh` runs offline `clai provision`)
- `codex/`, `copilot/`, `jules/` -- per-provider wrappers over `provision.sh`

## Providers

| Provider | Hook contract | Install location (manual) | Network assumptions |
|----------|---------------|---------------------------|---------------------|
| Codex cloud (setup) | Setup script runs once at container create, in the repo checkout | Codex web -> Environments -> setup script: `bash sandbox/codex/setup.sh` | ON -- the only guaranteed-egress phase; full bootstrap happens here |
| Codex cloud (resume) | Maintenance script runs on cached container resume | Codex web -> Environments -> maintenance script: `bash sandbox/codex/maintenance.sh` | MAYBE OFF -- runs `provision.sh --offline-ok`; cached state + staleness warning |
| Claude Code web/remote | Env Setup step runs pre-session; SessionStart hook runs synchronously before .mcp.json load (`CLAUDE_PROJECT_DIR` set, `CLAUDE_CODE_REMOTE=true`) | Env Setup script: `bash sandbox/claude-web/setup.sh` (runs `lmde acquire` -- installs clai + ast-mcp + the bundled skills/catalog from GitHub Packages, pre-session, #145); and/or register `sandbox/claude-web/session-start.sh` under `hooks.SessionStart` in `<repo>/.claude/settings.json` (runs OFFLINE configure-only `clai provision`) | ON at env-setup for `lmde acquire`; SessionStart `clai provision` is OFFLINE. Brokered GH_TOKEN cannot read GitHub Packages -- `lmde acquire` needs a classic `read:packages` `GH_AI_TOOLS_PAT` sandbox secret |
| Copilot coding agent | Job named exactly `copilot-setup-steps` in `.github/workflows/copilot-setup-steps.yml`, run before the agent starts | Copy `sandbox/copilot/copilot-setup-steps.yml` to `.github/workflows/` in the target repo; add `GH_AI_TOOLS_PAT` secret | ON during setup steps; job workspace starts EMPTY (Copilot clones for the agent only after setup steps), so the workflow performs its own `actions/checkout` |
| Jules | Per-repo environment setup script, runs in the VM before the agent | Jules repo configuration -> setup script: `bash sandbox/jules/setup.sh`; add `GH_AI_TOOLS_PAT` secret | ON at setup; no separate cached-resume hook surface |

Wrappers are installed into these provider hook locations MANUALLY by the
human, one provider at a time -- automating per-repo installation of
provider hooks is an explicit design non-goal. No OSS project abstracts
over provider-hosted sandbox setup contracts (surveyed 2026-07:
OpenSandbox, E2B, sandbox-agent et al. are self-hosted runtimes, a
different problem), so the per-provider nail gets hammered by hand.

## pins.env rollout note

`pins.env` is the single rollout lever: `provision.sh` sources it and `lmde
acquire --pins` reads it, so shipping new provisioning behavior everywhere is
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
- Session hook scripts ship inside the pinned clai package (installed by
  `clai hooks install`), so they roll out via the same `CLAI_VERSION`
  bump -- there is no separate hooks pin.

If `CLAI_VERSION` is ever reset to `UNSET`, `provision.sh` fails
LOUDLY-but-open: it logs the exact fill-in procedure and exits 0 so
sessions still start. Supply-chain integrity is npm's registry check
(every downloaded tarball verified against the published integrity hash)
plus the pinned, immutable version; the session is always fail-OPEN (every
terminal state exits 0).

Skills + the MCP catalog are NO LONGER floating inert data: post-#145 they
ride INSIDE the clai wheel's `_data`, so a skill or catalog edit reaches
sandboxes only after a clai RELEASE and a `CLAI_VERSION` bump here. That pin
bump IS the review gate for skills -- the accepted, WANTED consequence of
#145 (a skill edit is a reviewed change, not a silent default-branch push).
