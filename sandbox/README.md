# sandbox/ -- provider sandbox provisioning wrappers

Deliberately low-velocity wrappers that give every cloud-sandbox provider
the same session-start behavior: bootstrap a PINNED clai (fetch wheel from
the `9atatimer/ai-tools` release, verify sha256, install), then run the
idempotent `clai provision`. All behavioral churn lives inside clai,
behind the pins. See `docs/design/PROVISION.DESIGN.md` (issue #84) for the
full design; `.claude/hooks/session-start.sh` is the fetch/verify/fail-open
precedent these generalize.

## Layout

- `provision.sh` -- shared core; everything else is a thin veneer over it
- `pins.env` -- CLAI_VERSION, CLAI_SHA256, HOOKS_TAG, HOOKS_SHA256; the
  ONLY moving part (see rollout note below)
- `codex/`, `claude-web/`, `copilot/`, `jules/` -- per-provider wrappers

## Providers

| Provider | Hook contract | Install location (manual) | Network assumptions |
|----------|---------------|---------------------------|---------------------|
| Codex cloud (setup) | Setup script runs once at container create, in the repo checkout | Codex web -> Environments -> setup script: `bash sandbox/codex/setup.sh` | ON -- the only guaranteed-egress phase; full bootstrap happens here |
| Codex cloud (resume) | Maintenance script runs on cached container resume | Codex web -> Environments -> maintenance script: `bash sandbox/codex/maintenance.sh` | MAYBE OFF -- runs `provision.sh --offline-ok`; cached state + staleness warning |
| Claude Code web/remote | SessionStart hook, synchronous before .mcp.json load; `CLAUDE_PROJECT_DIR` set, `CLAUDE_CODE_REMOTE=true` | Register `sandbox/claude-web/session-start.sh` under `hooks.SessionStart` in `<repo>/.claude/settings.json` | ON at session start; brokered GH_TOKEN unusable against api.github.com -- needs `GH_AI_TOOLS_PAT` sandbox secret |
| Copilot coding agent | Job named exactly `copilot-setup-steps` in `.github/workflows/copilot-setup-steps.yml`, run before the agent starts | Copy `sandbox/copilot/copilot-setup-steps.yml` to `.github/workflows/` in the target repo; add `GH_AI_TOOLS_PAT` secret | ON during setup steps; repo already checked out (no checkout step needed) |
| Jules | Per-repo environment setup script, runs in the VM before the agent | Jules repo configuration -> setup script: `bash sandbox/jules/setup.sh`; add `GH_AI_TOOLS_PAT` secret | ON at setup; no separate cached-resume hook surface |

Wrappers are installed into these provider hook locations MANUALLY by the
human, one provider at a time -- automating per-repo installation of
provider hooks is an explicit design non-goal. No OSS project abstracts
over provider-hosted sandbox setup contracts (surveyed 2026-07:
OpenSandbox, E2B, sandbox-agent et al. are self-hosted runtimes, a
different problem), so the per-provider nail gets hammered by hand.

## pins.env rollout note

`pins.env` is the single rollout lever: every wrapper sources it via
`provision.sh`, so shipping new provisioning behavior everywhere is ONE
reviewed change -- the pin bump is the review gate (same supply-chain
stance as the ast-mcp hook and ai-tools issue #72: a push to a source
repo's default branch must never grant code execution in consumers).

The pins currently read `UNSET` on purpose:

- `CLAI_VERSION` / `CLAI_SHA256` are filled when the first clai release
  with the provision verbs (clai-vNEXT) is cut in `9atatimer/ai-tools`.
- `HOOKS_TAG` / `HOOKS_SHA256` are filled when hooks-v1 is tagged in
  `nine-at-a-time-media/template-tools`.

Until then `provision.sh` fails LOUDLY-but-open: it logs the exact
fill-in procedure and exits 0 so sessions still start during the rollout.
Once set, checksum verification is fail-CLOSED per artifact (a mismatch
refuses to install and removes the download) but always fail-OPEN for the
session (every terminal state exits 0).

Skills and the MCP manifest are inert data and deliberately NOT pinned --
they float to the latest default branch of `template-tools`.
