# LMDE Tech Radar

> Purpose: Snapshot of the LMDE's current tech choices and their rationale, to guide additions and prevent drift.
> When to use: Before adding tooling, services, or languages to the LMDE.
> Scope: tds-utils (the LMDE) only. Fleet defaults live in the tech-radar skill (template-tools/skills/tech-radar); this file is the repo-scoped radar it points to as the worked example.
> Update Discipline: MAINTAINED BY THE HUMAN. AI agents audit and propose changes, but do not commit edits to this file without explicit human approval.

---

## When to Consult This Radar

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
- **HAProxy**: The LMDE proxy layer -- the one local front door that every
  laptop service with a public port, or a shared queue, sits behind
  (`docs/design/OLLAMA-GATEWAY.DESIGN.md`, Deadline proxy). Chosen for its
  backend request queue with priority classes (`maxconn`,
  `http-request set-priority-class`, `timeout queue`), which the decision
  arena needs so interactive callers jump ahead of batch work (Issue#382).
  Homebrew-installed, loopback only.
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
  Per-project install under `~/.cache/<project>-cft/`. See the
  chrome-mcp skill (template-tools/skills/chrome-mcp) for the wiring
  pattern. First adopted in `ai-gm` Phase 0.5.

---

## Trial -- Testing in Limited Scope

- **MCP (Model Context Protocol)**: Evaluating for standardized agent tool-use.
- **skills** (Vercel, `vercel-labs/skills`, skills.sh): Homebrew-core CLI for
  installing third-party skill packs (`skills add <source>`) into an agent's
  skills directory. Ambient, like NATS -- ships via Homebrew, not the
  `lmde acquire` rail; no version pin, no fleet deployment. Unrelated to
  `@nine-at-a-time-media/skills` (this org's own inert skills-tree data
  package) despite the shared name.
- **TPM** (`tmux-plugins/tpm`), **tmux-resurrect**, **tmux-continuum**: tmux
  plugin manager plus session save/restore and autosave, declared in
  `log-hoarder/tmux.conf`. Installed by `git clone` (TPM) and `prefix + I`,
  which is unsigned code; hence Trial, cloned by hand and never implicitly.
  Exit criterion: a Homebrew or otherwise signed install path, or a
  restore-by-hand replacement.
- **Loki** (Grafana): log and event store in the observability kind
  cluster, fed OTLP logs by the collector. Single binary, digest-pinned in
  `lmde/components/registry/images.txt`. Exit criterion to Adopt: a month
  of local and cloud logs (issue #380) with retention holding the disk.
- **Tempo** (Grafana): trace store in the observability kind cluster, fed
  OTLP spans by the collector. Monolithic, digest-pinned beside Loki. Exit
  criterion to Adopt: same as Loki.
- **Decision models** (Jev, Clef and kin; Clef-flash is the recommended
  first model, not yet confirmed): a pretrained model reads a state once
  and a small head scores every option of typed questions -- yes/no,
  pick-one, rubric -- returning probabilities with no text generated. To be
  served on the laptop by the decision arena, behind the LMDE proxy layer
  and the Ollama Gateway's cloudflared road; none of it is built or
  installed yet. First consumer: the ocrinator's page decisions. Exit
  criterion: measured against a hand-adjudicated sample there, adopt or
  drop (Issue#382).

---

## Assess -- Researching / Observing

- **sqlite-vec**: Potential replacement for heavier embedding search frameworks in `log-hoarder`.
- **sesh**: tmux session manager (create-or-attach by name, zoxide/tmux/config-driven picker sources). Evaluating as the `tm` interactive alias's backend in place of a hand-rolled `tmux has-session` script.
- **zoxide**: Frecency-ranked `cd` replacement. Evaluating as a `sesh` picker source (recently/frequently visited dirs), not yet adopted as a `cd` replacement itself.
- **Docling** (IBM): document-to-structured-data conversion (PDF, DOCX, HTML -> Markdown/JSON with layout and tables). Evaluating as the ingestion front end for LLM-adjacent jobs that read documents.
- **Marker**: PDF -> Markdown converter with OCR and layout detection. Evaluating alongside Docling; one of the two, not both, would be adopted.

---

## Hold -- Avoid / Deprecated

- **bash on macOS**: Deprecated in favor of `zsh`.
- **GNU Coreutils on macOS**: Use BSD-first syntax to maintain macOS portability.
- **Hardcoded Secrets**: All secrets must go through `op` or Kubernetes Secrets; never checked into the repo.
- **Docker for Simple Services**: Prefer running services natively or in `kind` if they require K8s; avoid standalone `docker-compose` for permanent environment services.
- **Perl**: Legacy. Only used in `ipscan.pl`. No new development.

---

## Decisions Log

- **2026-10-03**: Adopted `HAProxy` as the LMDE proxy layer, at Todd's
  request ("I have ultimate confidence in it"). It settles the layer's
  proxy choice that `OLLAMA-GATEWAY.DESIGN.md` left open between nginx,
  haproxy and Caddy: only HAProxy queues requests to a busy backend with
  priority, which open-source nginx and Caddy do not (Issue#382). Caddy
  keeps its role as the `.localhost` TLS terminator.

- **2026-10-02**: Added `Loki` and `Tempo` to Trial on Todd's approval
  ("let's do it", issue #380): LMDE stored only metrics, so logs and
  traces, local or cloud, were not debuggable after the fact.

- **2026-10-02**: Added decision models to Trial at Todd's request, served
  locally by the decision arena (Issue#382). No installs or downloads yet.

- **2026-09-30**: Added `TPM`, `tmux-resurrect` and `tmux-continuum` to Trial
  at Todd's request, so log-hoarder terminals share one tmux session that
  survives a server restart.

- **2026-09-17**: Added `Docling` and `Marker` to Assess at Todd's request
  ("both seem interesting"); no consumer yet.

- **2026-09-07**: Added `skills` (Vercel CLI, Homebrew-core) to Trial.
  Ambient/unpinned like NATS -- not on the `lmde acquire` rail. See
  `docs/design/LMDE.DESIGN.md` section 6 (skills-drift indicator) and
  `lmde/LMDE.md`.

- **2026-09-06**: Added `sesh` and `zoxide` to Assess. Evaluating for a
  `tm` tmux create-or-attach alias (see `macos/dot.alias`).

- **2026-07-26**: Moved from `prompts/SKILL.TECH_RADAR.md` to
  `lmde/TECH_RADAR.md` as part of the `prompts/` retirement
  (issue #179). Radar *logic* now comes from the provisioned tech-radar
  skill; this file is the repo-scoped radar data it consults.

- **2026-05-23**: Adopted Chrome for Testing (via `chrome-devtools-mcp`)
  as the per-project pattern for agent-driven browser control. Rationale:
  Chrome 142+ silently disabled `--load-extension` for branded Chrome
  under `--enable-automation`; CfT is exempt. Pattern lives in the
  chrome-mcp skill; not LMDE contract because each project gets its own
  profile, version, and extension loadout.

- **2026-05-21**: Formalized LMDE architecture and Observability stack.
- **2026-05-18**: Initial Tech Radar design conversation (see `docs/design/WIP.TECH_RADAR.DESIGN.md`).
