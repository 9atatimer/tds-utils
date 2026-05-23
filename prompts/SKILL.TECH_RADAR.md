# SKILL: LMDE Tech Radar

> Purpose: Snapshot of the LMDE's current tech choices and their rationale, to guide additions and prevent drift.
> When to use: Before adding tooling, services, or languages to the LMDE.
> Scope: tds-utils (the LMDE) only. Per-project stacks live in template-tools.
> Update Discipline: MAINTAINED BY THE HUMAN. AI agents audit and propose changes, but do not commit edits to this file without explicit human approval.

---

## When to Invoke This Skill
- About to add a new CLI tool, language, or local service to the LMDE.
- Considering replacing or removing existing LMDE tech.
- Evaluating a new AI/agent tool, MCP server, or skill pattern.
- Onboarding a new machine and questioning a default.
- **NOT** for per-project tech (e.g., choice of database for a specific app).

## Adopt -- Current Platform Standards

These technologies are the foundational components of the Local Managed Developer Environment (LMDE). They form a stable contract that other projects can rely upon.

### Languages & Runtimes
- **zsh**: Primary shell on macOS. Chosen for rich interactive features and macOS defaults.
- **bash**: Primary shell on Linux. Chosen for ubiquity and standard automation.
- **Node.js (MJS)**: Used for sophisticated environment orchestration (e.g., `gadmin`). Chosen for asynchronous I/O and GitHub API ecosystem.
- **Python 3**: Used for data processing and search tasks (e.g., `log-hoarder`). Chosen for standard library and text handling.
- **Go**: Used for systems-level CLI tools. Chosen for static binaries and performance.

### Core Infrastructure
- **1Password CLI (op)**: Source of truth for secrets and identity.
- **NATS**: Distributed message bus for local service inter-op. Standardized on `localhost:4222`.
- **Caddy**: Local reverse proxy and TLS terminator.
- **dnsmasq**: Local DNS orchestration for `.localhost` and internal discovery.
- **Local Registry**: Secure container mirror on `localhost:5001`.

### Editor & Multiplexer
- **Emacs**: The primary digital workspace. Extensively customized via `init.el`.
- **tmux**: Standard terminal multiplexing and session persistence.

### AI & Agents
- **Ollama**: Local LLM inference server.
- **remollama**: Remote orchestration and proxying for Ollama.
- **OpenTelemetry (OTel)**: Standardized destination for agent metrics and traces.

### Development Platforms
- **kind**: Kubernetes in Docker for local cluster orchestration. Standardized boundary for complex services (like Observability).

### Per-Project Patterns (Recommended, not LMDE contract)
Tooling patterns adopted for use *within* projects rather than as LMDE
platform components. Each project installs its own; this section
documents the recommended approach so it isn't reinvented per repo.

- **Chrome for Testing (via `chrome-devtools-mcp`)**: Stand-alone
  Chromium binary for giving an agent driveable control of a browser
  without enabling remote debugging on the user's main Chrome.
  Per-project install under `~/.cache/<project>-cft/`. See
  `@nine-at-a-time-media/prompts` `SKILL.CHROME_MCP.md` for the wiring
  pattern. First adopted in `ai-gm` Phase 0.5.

---

## Trial -- Testing in Limited Scope
- **MCP (Model Context Protocol)**: Evaluating for standardized agent tool-use.

---

## Assess -- Researching / Observing
- **sqlite-vec**: Potential replacement for heavier embedding search frameworks in `log-hoarder`.

---

## Hold -- Avoid / Deprecated
- **bash on macOS**: Deprecated in favor of `zsh`.
- **GNU Coreutils on macOS**: Use BSD-first syntax to maintain macOS portability.
- **Hardcoded Secrets**: All secrets must go through `op` or Kubernetes Secrets; never checked into the repo.
- **Docker for Simple Services**: Prefer running services natively or in `kind` if they require K8s; avoid standalone `docker-compose` for permanent environment services.
- **Perl**: Legacy. Only used in `ipscan.pl`. No new development.

---

## Decisions Log
- **2026-05-23**: Adopted Chrome for Testing (via `chrome-devtools-mcp`)
  as the per-project pattern for agent-driven browser control. Rationale:
  Chrome 142+ silently disabled `--load-extension` for branded Chrome
  under `--enable-automation`; CfT is exempt. Pattern lives in
  `@nine-at-a-time-media/prompts` `SKILL.CHROME_MCP.md`; not LMDE
  contract because each project gets its own profile, version, and
  extension loadout.
- **2026-05-21**: Formalized LMDE architecture and Observability stack.
- **2026-05-18**: Initial Tech Radar design conversation (see `docs/design/WIP.TECH_RADAR.DESIGN.md`).
