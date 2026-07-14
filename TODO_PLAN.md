# TODO_PLAN.md

This file tracks the status of development tasks, lessons learned, and completed work for the `tds-utils` repository.

## How to use this file
1. **Open Tasks**: Add new tasks here. Use checkboxes `[ ]` for pending and `[x]` for completed tasks.
2. **Lessons Learned**: After finishing a task or encountering a significant issue, document the insight here.
3. **Completed Tasks**: Move finished tasks from the "Open Tasks" section to this section.

---

## Open Tasks

### Universal Agent Provisioning -- issue #84 (phase entry, 2026-07-04)

Implementation of `docs/design/PROVISION.DESIGN.md`: every new agent
session self-provisions skills, MCP configs, and hook scripts from the
canonical sources (`template-tools` data floats; clai wheel + hook scripts
are pinned and checksum-verified).

Done in this repo (this phase):

- [x] `sandbox/` wrapper tree: `provision.sh` shared core (bootstrap pinned
  clai wheel via gh/PAT, verify sha256 fail-closed per artifact, install
  via uv/pip, exec `clai provision`; fail-open at session level),
  `pins.env` (the only moving part; pins UNSET until the releases exist),
  per-provider wrappers (`codex/setup.sh`, `codex/maintenance.sh`,
  `claude-web/session-start.sh`, `copilot/copilot-setup-steps.yml`,
  `jules/setup.sh`), and `sandbox/README.md`.
- [x] `.claude/hooks/session-start.sh`: clai-provision branch added ahead
  of the remote-gated ast-mcp flow (`clai provision --offline-ok` when
  clai is on PATH; non-fatal), header updated to mark it as a
  tds-utils-local addition to the vendored copy.
- [x] `clai.d/mcp.json`: this repo's manifest layer (`{"profiles":
  ["base"]}`) for the canonical-manifest overlay walk.
- [x] `docs/design/PROVISION.DESIGN.md` (the design this implements).

Done elsewhere (companion changes in sibling repos, same rollout):

- [x] `template-tools`: canonical `skills/<name>/SKILL.md` tree, canonical
  `mcp/manifest.json`, and `hooks/` session hook scripts.
- [x] `ai-tools`: clai `provision` / `refresh` / `hooks install` verbs
  (reserved-verb carve-outs in `cli.py`).

Remaining:

- [x] Task P1: **Fill `sandbox/pins.env`.** Done 2026-07-04: clai-v0.5.0
  released from the merged 9atatimer/ai-tools#89; CLAI_VERSION=0.5.0 and
  CLAI_SHA256 (wheel digest from the release API) landed via PR. Future
  bumps repeat the same pin-bump-via-PR flow -- the pin bump is the
  review gate.
- [ ] Task P2: **Manual per-provider wrapper installation.** Todd installs
  the `sandbox/` wrappers into each provider's hook surface (Codex
  environment setup/maintenance scripts, Claude web SessionStart hook
  registration, `.github/workflows/copilot-setup-steps.yml` +
  GH_AI_TOOLS_PAT secret, Jules environment setup script). Explicitly a
  design non-goal to automate.
- [ ] Task P3: **`prompts/` retirement.** After provision is live and the
  migrated skills prove out, retire the flat `prompts/SKILL.*.md` channel.
  Keep `prompts/` untouched until then.
- [ ] Task P4: **ast-mcp startup race -- install at env-setup, not the
  SessionStart hook.** GH Issue #99. Delivery is fixed (#98, GitHub Packages)
  but the server doesn't connect on first session load: Claude Code attempts
  the MCP connection concurrently with the SessionStart hook, and the hook's
  `npm install` hasn't finished writing the binary yet -> first spawn ENOENTs,
  no retry, server absent until a later reconnect. Move the ast-mcp install
  into the environment SETUP step (runs before session init) so the binary
  exists when MCP first connects; keep the SessionStart hook as an idempotent
  refresh/fallback. Decide user-scope (`~/.claude.json`) vs project `.mcp.json`.
- [ ] Task P5: **clai bootstrap via GitHub Packages.** GH Issue #101.
  `sandbox/provision.sh` still fetches the clai wheel over the proxy-blocked
  `api.github.com` release-asset path, so clai provisioning fails in every
  Claude web session. clai is now published to GitHub Packages
  (`@nine-at-a-time-media/clai`, an npm wrapper around its shiv `.pyz`); rework
  `bootstrap_clai` to `npm install` it from Packages, mirroring the #98 ast-mcp
  fix (classic `read:packages` token; ephemeral mode-600 `.npmrc`; fail-open).

### Offline Readiness & Local LLM Hardening

- [ ] Task OR1: **goldfish: Improve LLM robustness and model fallback.** Implement automatic detection of available local Ollama models if `GOLDFISH_OLLAMA_MODEL` is unset. Fall back to `claude` if available and `ollama` is not. GH Issue #59.
- [ ] Task OR2: **log-hoarder: Transition from txtai to Ollama-native embeddings.** Move to an Ollama-powered `EmbeddingPort` using `/api/embed`. Default to `nomic-embed-text`. GH Issue #60.
- [ ] Task OR3: **clai: Implement offline/local-only mode.** Add an `--offline` flag to skip remote connectivity checks and prioritize local Ollama shims. GH Issue #61.

### gadmin tasks (MOVED)

~~These tasks referred to the `gadmin/` tools formerly in this repo. They have been relocated to `Nine-At-A-Time-Media/template-tools/packages/naatm-admin` and are no longer actionable in `tds-utils`.~~

- ~~Task GA1: Stale path comments in moved headers.~~
- ~~Task GA2: `pr-comments --detailed` parser breaks on pipes/newlines.~~
- ~~Task GA3: jq quote-injection from user-supplied workflow / job names.~~
- ~~Task GA4: `listJobsForWorkflowRun` not paginated.~~
- ~~Task GA5: `parseArgs` mishandles values that start with `--`.~~
- ~~Task GA6: `cmd_pending_comments` doesn't validate resolved repo/PR.~~
- ~~Task GA7: Dispatcher's `github-*` fallback alias leak.~~

### gadmin Issues -- remaining design goals

The gadmin Issues subsystem shipped a working v0 skeleton (grammar, aggregator, SQLite snapshot, event publish, phase A/B/E/F commands, GH-poll `--wait-tx`, launchd/systemd units, 7 smoketests). Five v0 goals from `docs/design/GADMIN-ISSUES.DESIGN.md` are not yet implemented. Status snapshot lives in that doc's [Implementation Status](docs/design/GADMIN-ISSUES.DESIGN.md#implementation-status) section.

- ~~Task GI1: NATS request-reply reads.~~
- ~~Task GI2: NATS-first `--wait-tx`.~~
- ~~Task GI3: `gh webhook forward` as primary ingress.~~
- ~~Task GI4: `gadmin.health` request-reply subject.~~
- ~~Task GI5: Backend peer routing via `$GADMIN_BACKEND`.~~

### gadmin review-watch tooling (MOVED)

- ~~Task GR1: Implement `gadmin github review-state --pr <N>` verb.~~
- ~~Task GR2: `gadmin pending-comments`: defer branch-mismatch guard.~~

### LMDE (Local Managed Developer Environment)

- [ ] Task LMDE7: **Events: design reconcile.** Revise `docs/design/LMDE-OBSERVABILITY.DESIGN.md` -- refine the "Log Aggregation" Non-Goal (structured OTLP events in scope; raw terminal logs stay `log-hoarder`'s), add the Loki events architecture, note Tempo as the deferred traces leg.
- [ ] Task LMDE8: **Events: Loki component.** Pin the Loki image(s) in `images.txt`; add a single-binary `grafana/loki` component under `specs/loki/` with HostPath persistence.
- [ ] Task LMDE9: **Events: collector logs pipeline.** Add a `logs` pipeline to the otel-collector config, exporting OTLP logs to Loki's OTLP endpoint.
- [ ] Task LMDE10: **Events: Grafana datasource + bootstrap + verify.** Add the Grafana Loki datasource, install Loki in `setup.sh`, and smoke-test an OTLP event end to end.
  - Note: the events pipeline stays inert until clai sets `OTEL_LOGS_EXPORTER=otlp` (in `ai-tools`, not this repo) -- coordinate before declaring LMDE10 done.
- [ ] Task LMDE11: **Stack-health Grafana dashboard.** Add a Grafana dashboard monitoring the obs stack itself -- CPU, memory, storage, restarts/errors per component (prometheus, grafana, otel-collector, loki, ingress-nginx). Dashboard JSON + ConfigMap; no new infra; can land before LMDE7-10.
- [ ] Task LMDE12: **NATS-in-kind: design.** Draft `docs/design/LMDE-BACKPLANE.DESIGN.md` -- move the LMDE backplane (starting with NATS, then audit each other Adopted component against the residency rule in `lmde/LMDE.md`) into the kind cluster behind LMDE5's ingress-nginx + `*.lmde.localhost`, so kind-sandboxed coding agents reach the same bus as Mac-local agents. Decide: NATS server in-cluster vs. exposing host NATS via ingress; auth model (anonymous loopback today vs. per-agent creds); how `gadmin` and other clients resolve the bus address from inside vs. outside the cluster; which components actually need to move (Caddy/dnsmasq/registry sit at the edge or feed kind and may stay out). Update the `lmde/LMDE.md` Contract once the design lands.
- [ ] Task LMDE13: **NATS-in-kind: implement.** Add `lmde/components/nats/` (kind manifest + `setup.sh`), pin the image digest in `lmde/components/registry/images.txt`, register `nats.lmde.localhost` via the LMDE5 ingress helper, and add a `test/smoketest_lmde_nats/` smoke that pub/subs from both the host and an in-cluster pod. Depends on LMDE12.

### Goldfish

- [x] Task G10: **smoketest hermeticity: `resolve_orgs()` falls through to real `gh`.** Scenarios 01/05/06 fail because when smoke config has `"orgs": []`, `resolve_orgs()` runs `gh api user --jq .login` and uses the real user's login, polluting the smoke env with real GitHub data (which then hides the test fixtures behind the actionability filter). Fix: added a `--no-gh` flag to goldfish and updated the smoke runner to use it + `--no-filter`. PR #59.

### Terminal UX

- [x] Task T1: **Improve brand theme matching** -- currently it does a literal case-insensitive match. If "Solarized Dark" is a theme, `brand solarized` fails. Add a fuzzy or substring match for theme names. PR #57.

### UX / Interaction Quality (high-friction issues with the current proof-of-concept)

- [ ] Task U0: **Purge sampling terminology and code.** The `get_log_sample()` function in `search/cli/index.py`, the `sample_logs()` function in `log_brander`, `content_sample` field on `LogEntry`, and the `"text"` construction in `TxtaiAdapter.add_entries()` all embody a "sample a few lines to represent a session" approach that is fundamentally wrong for semantic search and confusing to maintain. Remove or rename: `content_sample` → remove from `LogEntry` (chunked pipeline replaces it), `get_log_sample()` → delete (Tasks 2b-2e replace it), `sample_logs()` in `log_brander` → rename to `extract_branding_context()` (brander legitimately needs a summary, but should not call it a "sample"). Clean up any references in comments and docstrings.
- [ ] Task U1: **Search latency -- eliminate process-per-keystroke startup cost.** Every fzf `change:reload` spawns a new Python process that loads the txtai embedding model from disk. This is the dominant cause of dropped characters and sluggish response. Needs a long-running search process (daemon, UNIX socket, FIFO, or similar) so fzf reloads talk to a warm model. Design doc should specify the approach.
- [ ] Task U2: **Preview pane should show the matching region.** Currently `head -c 4000 {1}/*.log | head -80` shows the top of the file, which has no relationship to why it ranked high. Once chunk-level search (Tasks 2d-2f) produces byte offsets, update `log_search` output format and the ZLE widget's `--preview` command to extract the matching byte range from the source log. Depends on Tasks 2d-2f.
- [ ] Task U3: **Selecting a result opens multiple files in $PAGER.** The ZLE widget globs `*.log(N)` on the pane directory and passes all matches to `$PAGER`. A pane dir can accumulate multiple `.log` files from reuse across tmux sessions. Need to either: (a) resolve search results to a specific `.log` file (not just the pane dir), or (b) concatenate with clear separators, or (c) open only the file containing the matching byte range. Depends on chunk-level search output.
- [ ] Task U4: **Search result display lines are unreadable.** The fzf result list shows raw archive paths (`/Users/stumpf/.local/share/log-hoarder/archived/1/1/0`) which are meaningless to a human. Display should show: slug (if branded), tail 2-3 directory components of the working dir at span start, compact datetime, and optionally the tmux window name. The preview pane provides full context -- the result line just needs to be scannable.

### Smoke Test & CLI (drives everything below -- write tests first, then build until they pass)

- [x] Task S1: Create `log_search` CLI -- the entry point for both the ZLE widget and the smoke test. Takes a query string, prints ranked results (session path, working dir, timestamp, preview). Lives in `bin/log_search` and delegates to the Python search pipeline.
- [x] Task S2: Create smoke test harness `test/smoketest_log_search/` -- shell scripts following the grubsta pattern (`config.sh`, `run_all.sh`, numbered scenario scripts). Tests run against real `$TDS_LOG_DIR/archived/` data.
- [x] Task S3: Smoke test scenario -- `01_index_archived_logs.sh` -- run the indexer against real archived logs, assert exit 0 and index is non-empty. Setup for all subsequent tests.
- [x] Task S4: Smoke test scenario -- `02_keyword_match.sh` -- `log_search "ollama"` returns a result pointing to a session that contains "ollama" (sessions 2/1/0 and 3/0/0 both have ollama activity).
- [x] Task S5: Smoke test scenario -- `03_semantic_match.sh` -- `log_search "checking environment variables for a running service"` returns a result pointing to the launchctl/OLLAMA session (1/1/0) even though the query doesn't share exact keywords.
- [ ] Task S6 (future): Smoke test scenario -- project-scoped search. `log_search "git clone in 9atatimer"` returns session 2/2/0 (which has `cd workplace/9atatimer && git clone`). Requires working dir context in embeddings.
- [ ] Task S7 (future): Smoke test scenario -- cross-project filter. Same query scoped to a different project returns different/no results.
- [ ] Task S8 (future): Smoke test scenario -- search across compressed and uncompressed logs returns consistent results.

### Shell Integration

- [x] Task Z1: Create ZLE widget for `ctrl-x s` -- invokes `log_search`, pipes results through `fzf` for selection, displays matched log section in `$PAGER`. Plugin file `macos/dot.zsh_log_search`, sourced from `dot.zshrc`. PR #12.

### log-hoarder / tmux UX

- [ ] Task L2: **Adopt meaningful session names** -- default numeric (`18`, `19`, `20`…) make `tmux ls` and the new title-string both worse than they need to be.
- [ ] Task L3: **Handle session-rename → log-path drift** -- `tmux_logging.sh` bakes `#S` at pipe-pane time, so renaming a live session splits its logs across old and new dirs.

### Pipeline (implementation work driven by smoke tests above)

- [ ] Task 2b: Implement `Segmenter` -- reads log text, detects span boundaries (prompt lines with cd, tool switches, idle gaps), returns `Span` objects with byte offsets. Pure domain logic in `search/domain/segmenter.py`. Should accept text, not file paths -- keeps it pure for future compression abstraction.
- [ ] Task 2c: Implement `Chunker` -- splits a span's text into embedding-sized `Chunk` objects with overlap. Pure domain logic in `search/domain/chunker.py`.
- [ ] Task 2d: Update `SearchIndexPort` and `TxtaiAdapter` -- store chunk embeddings keyed by `session:span:chunk` with byte-offset metadata. Add `EmbeddingPort` to `ports.py`.
- [ ] Task 2e: Update indexer -- replace `get_log_sample` with full pipeline: read log → segment into spans → chunk each span → embed → store. Move `indexer.py` into `search/`.
- [ ] Task 2f: Update searcher -- query returns chunk hits, group by span, return ranked span references. Move `searcher.py` into `search/`.
- [ ] Task 3: Wire `log_search` CLI to the searcher. Get smoke tests S4 and S5 passing.
- [ ] Task 4: Integrate indexer into `tmux_shepherd.sh` cron mode.
- [ ] Task 5: Phase 2 -- Implement `SqliteVecAdapter` + `OllamaAdapter` for lighter-weight alternative.
- [ ] Task 6 (future): Compressed log storage -- implement compression in archive pipeline, update file-access abstraction, get smoke test S8 passing.

### Security / Credentials

- [ ] Task SEC1: **Rotate the GitHub Packages PAT in `~/.npmrc` and switch to a non-plaintext source.** Current state: a read-only PAT sits cleartext in `~/.npmrc` (`//npm.pkg.github.com/:_authToken=ghp_...`) and was emitted twice into a Claude transcript during a Mini Shai-Hulud audit (CVE-2026-45321, 2026-05-11). Replace with shell wrappers around `npm`/`pnpm`/`yarn`/`npx` that hydrate `${GITHUB_PACKAGES_TOKEN}` at call time. Preferred source: `gh auth token` (gh's own creds live in macOS keychain). Fallback: `security find-generic-password -s github-packages-pat -a 9atatimer -w`. The `.npmrc` line becomes `${GITHUB_PACKAGES_TOKEN}` so no secret on disk. Wrappers land in `bash/dot.bashrc.d/` (or `macos/` if zsh-only). Read-only scope limits blast radius but the token is functionally burned; rotate at revoke time.

### Style / Docs

- [x] Task SD1: **`prompts/`-wide SKILL.MARKDOWN.md compliance sweep.** Several files (incl. `prompts/GITHUB.md`) skip the blank-line-before-lists rule from `prompts/SKILL.MARKDOWN.md:17`. Also clean up stale Unicode -- e.g. `~5-10x` on `prompts/GITHUB.md:69` (en-dash + multiplication sign) violates the ASCII-only-prose rule from `SKILL.MARKDOWN.md:12` and `SKILL.DESIGN.md:93`. One sweep across the directory is more honest than per-comment fixes in PR review. (Surfaced during PR #54 review-watch loop, but scope is broader than that PR.) PR #58.

---

## Lessons Learned

- **Keep test fixtures free of legacy identifiers**: When writing test cases for leak detectors, ensure that fixture data uses purely synthetic placeholders (e.g., `user@tw-192-0-2-100.office.example.invalid`) instead of real identifiers from the private audit findings, preventing legacy leaks from being reintroduced.
- **Untracking pre-existing files in .gitignore**: Files committed before a matching `.gitignore` rule was added remain tracked. They must be explicitly untracked via `git rm --cached` to stop tracking.
- **Copilot coding-agent MCP config is read-only via the GitHub API** (#95): `GET /repos/{owner}/{repo}/copilot/cloud-agent/configuration` returns the coding agent's `mcp_configuration`, but there is **no write endpoint** -- the server list is UI-only (repo Settings -> Copilot -> Coding agent). So a `clai provision` "apply" for Copilot is unbuildable today; the one writable Copilot surface (`COPILOT_MCP_*` Agents secrets/variables) is orthogonal since the manifest carries no secret values. Lesson: probe an agent's *actual* config surface before designing an emitter; when it cannot be applied, be **vocal** (raise a MANUAL-ACTION warning) rather than silently no-op, and leave a clean seam for a future write adapter. `emit_copilot` implements this in clai (template-tools).
- **Dynamic Agent Skills Caching**: Dynamic prompt/skill cache directories populated by the agent CLI at runtime (`.agents/`, `.claude/skills/`, `.codex/`) should be ignored by the repository's `.gitignore` to avoid polluting `git status`, while keeping the configuration files (`.claude/settings.json`) and session hooks (`.claude/hooks/session-start.sh`) checked in for native tool discovery.
- **tds-utils is a Kernel, not a Utility Repo**: This repository represents the "soul in digital form" of the developer environment. It justifies a higher degree of architectural ceremony (ADRs, Tech Radar, Formal Design Docs) than a simple collection of scripts would, as it provides the foundation for all other work.
- **Architecture over Utilities**:
 Distinguishing between architectural components (LMDE) and personal configurations/utilities simplifies the platform contract and ensures projects can assume a stable foundation.
- **Supply-Chain Security via Local Mirroring**: Local mirroring with SHA256 digest pinning is a robust way to ensure environment stability and security on a developer laptop, making it resistant to upstream registry outages or poisoning.
- **Host-Path Persistence in kind**: Using host-path mapping for `kind` nodes is the most pragmatic way to ensure data persistence (like Prometheus metrics) survives cluster recreations and host reboots.
- **Securing Log Permissions**:
 Use `umask 077` at the start of logging and management scripts to ensure new directories and files are restricted to the owner. Perform a recursive `chmod -R u+rwX,go-rwx` on the log directory in management scripts like `tmux_shepherd.sh` to fix existing permissions without making non-executable files executable.
- **Hexagonal Architecture**: Decoupling the search index interface (`SearchIndexPort`) from the implementation (`TxtaiAdapter`) allows for an easy swap from a "heavy" framework like `txtai` to a lighter one like `sqlite-vec` later, while keeping the core logic intact.
- **Single Source of Truth (target state)**: The index will store only embeddings and metadata (session path, span ID, chunk index, byte offsets). The original log files are the sole content store. No raw text in the index, no sampling or truncation -- every byte of every log must be covered by embeddings. Note: the current MVP scaffolding still uses content sampling; Task 2a-2f replaces this with span-based chunked indexing.
- **Full Coverage Required**: A single session may span multiple projects and tasks. Sampling head/tail lines is useless for semantic search -- the indexer must segment into spans and chunk the entire file.
- **Spans vs Chunks**: Chunks are the unit of embedding (sized for the model's context window). Spans are the unit of retrieval (logically coherent stretches of activity). Search returns span references; chunks are an implementation detail of the index.
- **Byte Offsets Reference Uncompressed Content**: All byte offsets in `Span` and `Chunk` models reference the uncompressed log stream. This keeps the index format stable regardless of whether the underlying file is compressed or not. Log-reading code should go through a single file-access abstraction so compression can be added in one place later.
- **Frozen Dataclasses with Validation**: Using `@dataclass(frozen=True, slots=True)` with `__post_init__` validation catches invalid state at construction time. The `Chunk.from_span()` factory enforces that chunk byte ranges fall within their parent span -- this is a domain invariant, not just a nice-to-have.
- **Real Log Format**: Log lines follow the pattern `HH:MM:SS user@host:dir % command`. Prompt lines with `% cd` are the primary span boundary signal. Logs range from 3KB (short sessions) to 8.8MB (long benchmarking runs). The segmenter will need to handle heavy non-printable/control character noise from terminal output (tab completion artifacts, ANSI remnants post-ansifilter).
- **Test Behavior, Not Implementation**: Domain models (dataclasses, validation, properties) are implementation details -- testing them in isolation is change-detection, not bug-detection. Smoke tests should exercise the user-visible behavior: "I type a query, I get back the right session." Write that test first, then build until it passes. Unit tests for internal components only earn their keep if they test a behavioral contract that matters to the pipeline.
- **Smoke Tests Hit Real Systems**: A smoke test runs the real tool against real data and checks real output. Hardcoded fixtures pretending to be real data are just unit tests with extra steps. Smoke tests for log search run against `$TDS_LOG_DIR/archived/` and skip gracefully when unavailable.
- **`git status --porcelain=v1 -b` lies about fresh repos**: A repo with no commits prints `## No commits yet on <branch>`, not `## <branch>`. A naive `^##\s+(\S+)` branch regex captures `No`. Special-case the `No commits yet on ` prefix or every freshly-init'd repo gets mis-labeled. (Discovered while building goldfish.)
- **`/proc/<pid>/comm` is the binary basename, not `argv[0]`**: When the kernel does `execve`, it sets `comm` from the path of the executable, not what `argv[0]` says it is. Faking a renamed process for a test (e.g. a stand-in `claude`) requires `prctl(PR_SET_NAME, b"claude")` -- `os.execvp('bash', ['claude', ...])` doesn't work. Real-world flip side: an agent invoked through a wrapper script (e.g. `python3 launcher.py` that re-execs the real binary) presents `comm=python3` and slips past any name-based whitelist. Keep agent whitelists permissive, or match on cwd + open-fds instead of `comm`.
- **Terminal Branding via AppleScript/tmux**: Programmatically changing macOS Terminal themes requires `osascript` to talk to Terminal.app profiles. Combining this with `tmux set-option @brand` allows for a "dual-layer" branding where the theme is global to the tab but the title bar dynamically updates as you switch tmux windows. Conditional tmux formatting (`#{?@brand...}`) can then be used to hide the CWD prefix only when a brand is active.
- **Loop wakeups must stay inside the 5-min prompt-cache TTL**: Anthropic's prompt cache has a 5-min TTL; wakes <= 270s stay warm and cost almost nothing per iteration. The 300-1200s range is "worst of both" -- you pay the cache miss without amortising the wait. Codified globally in `~/.claude/CLAUDE.md` as a 240s hard ceiling, 90-180s default for active polling. (Surfaced when an in-flight 600s wake was clearly worse than the 120s alternative that would have caught a Copilot response sooner *and* cheaper.)
- **`gh pr edit --add-reviewer @copilot` (2026-03) is the only programmatic Copilot trigger**: The standard REST `requested_reviewers` endpoint rejects `copilot-pull-request-reviewer` with HTTP 422 "not a collaborator" -- the bot isn't actually added to repos when org-level Copilot review is enabled. The `@copilot` shorthand in `gh pr edit` is a CLI special-case that hits a different internal endpoint. Without this, Copilot doesn't auto-re-review on `synchronize` events and review-watch loops stall at "Copilot has fallen silent" waiting for the human to click the re-request button.
- **`gadmin pending-comments` silently aborts on branch mismatch even with explicit `--repo`/`--pr`**: The guard prints a warning, exits 1 without fetching anything, and hides real pending comments. Long-running agent loops that wake on arbitrary branches must `git switch` to the PR's head branch before any gadmin call, or the loop will report "0 pending" when Copilot has actually queued substantive feedback. Follow-up: Task GR2 above.
- **Two blind spots in poll-mode PR-review detection**: `gh pr view --json reviews` catches top-level reviews (including overview-only `state=COMMENTED` bodies) but doesn't surface standalone inline comments. `gadmin github pending-comments` catches standalone inline comments (e.g., human replies on existing threads) but doesn't surface overview-only reviews. A complete poll calls BOTH endpoints every wake; never short-circuit one based on the other. Codified in `prompts/GITHUB.md`'s Review-watch loop section.
- **Claude Review via clai**: Claude Code can be invoked non-interactively via `clai claude -p "<prompt>"`. This is useful for automated design reviews during flight sessions with limited battery.
- **Goldfish Hermeticity**: Smoke tests using `config.json` with `"orgs": []` must explicitly disable the `gh api user` fall-through via a `--no-gh` flag to avoid polluting the test environment with real user data.
- **TCP Ingress Logic**: `ingress-nginx` TCP snippets are raw pass-through; TLS termination must be handled by the host-side proxy (Caddy) or the backend (NATS), not blindly assumed at the ingress level. Decided to use Caddy as the unified LMDE host edge.
- **eltainer is the successor to eldocker**: Migrating involves updating load-paths in Emacs and ensuring the fork and upstream are correctly configured. eltainer talks directly to the Docker daemon and Kubernetes API via Elisp.
- **Pinned code vs floating data (provisioning split)**: Every EXECUTABLE artifact (clai wheel, session hook scripts) is version-pinned and sha256-verified before use -- fail-closed per artifact, and the pin bump in `sandbox/pins.env` is the review gate. Inert DATA (skills, MCP manifest) floats to the latest default branch so freshness is automatic. This extends the supply-chain stance from the ast-mcp hook / ai-tools issue #72: a push to a source repo's default branch must never grant code execution in consumers, but stale prompt data is a real cost worth avoiding. **Superseded by #145 (2026-07):** the DATA no longer floats -- skills + the MCP catalog now ride INSIDE the pinned clai wheel as `clai/_data` (content-stamped, materialized offline by `clai provision`), so a skill/catalog edit reaches sandboxes only after a clai release + a `CLAI_VERSION` bump in `sandbox/pins.env`. The split is now pinned-code-AND-pinned-data; the pin bump is the single review gate for both. First release carrying the bundled-data contract: clai 0.6.0 (template-tools#167).
- **No OSS abstraction over provider sandbox hooks (surveyed 2026-07)**: Codex, Claude Code web, Copilot coding agent, and Jules each have incompatible pre-agent hook contracts, and no OSS project abstracts over provider-HOSTED sandbox setup (OpenSandbox, E2B, sandbox-agent et al. are self-hosted runtimes -- a different problem). Consequence: keep per-provider wrappers thin and manually installed, and concentrate all behavioral churn behind one pinned core (`sandbox/provision.sh` + `pins.env`).
- **The Claude Code web proxy blocks raw GitHub release-asset egress (2026-07, #98/#99)**: In Claude web sandboxes the agent proxy returns a synthetic 403 for `api.github.com/.../releases` and a 404 for `github.com/.../releases/download/*` -- regardless of token. The whole "fetch the release `.tgz`/wheel + verify a paired `.sha256`" delivery model is therefore DEAD in Claude web. The reachable, sanctioned channels are: the GitHub MCP server, git-over-proxy, and -- critically -- the **GitHub Packages npm registry (`npm.pkg.github.com`)**. Delivery for the whole fleet moved onto GitHub Packages as a result.
- **GitHub Packages npm reads require a CLASSIC `read:packages` token (2026-07, #98)**: Fine-grained PATs have NO Packages permission at all, so they 403 against `npm.pkg.github.com` ("token does not match expected scopes"). This reverses the design's original "fine-grained Contents:read PAT" assumption. `GH_AI_TOOLS_PAT` is now a classic `read:packages` token. (Delivery no longer needs repo Contents access -- the artifact comes from the registry, not a git checkout.)
- **Ship Python tools as npm wrappers on GitHub Packages (2026-07, template-tools#73)**: clai/crmagic/designomatic each build a self-contained shiv `.pyz`; wrapping that pyz in a thin node package (bin -> pyz; `SHIV_ENTRY_POINT` for alias entries) lets the ENTIRE fleet -- ast-mcp, the Python CLIs, and the `naatm-*` packages -- install the same way: one `npm install` from GitHub Packages, one classic `read:packages` token. GitHub Packages has no PyPI feed, so this npm-wrapper is how Python artifacts ride the same rail.
- **A SessionStart hook cannot be the install point for an MCP-server binary (2026-07, #99)**: Claude Code attempts `.mcp.json` server connections concurrently with SessionStart hooks. A hook that INSTALLS the server binary loses the race -- the binary isn't on disk when MCP first tries to spawn it (ENOENT, no auto-retry), so the server shows absent until a later reconnect. Corollary to the design's "config must be written before the agent launches": writing the config early is necessary but not sufficient; the binary it points at must ALSO exist before session init. MCP-server binaries must be installed in the environment SETUP step (pre-session); the SessionStart hook is a refresh/fallback, not the first-connect installer.
- **`.mcp.json` `${VAR}` indirection only resolves vars present in the MCP-server PROCESS (2026-07, #98)**: The original `"command": "${AST_MCP_BIN}"` failed because `AST_MCP_BIN` is exported only by interactive shell dotfiles, which the MCP client process never sources -> it expanded empty and the server never launched. Claude Code sets `CLAUDE_PROJECT_DIR` and `HOME` in the spawned server's env and supports `${VAR:-default}`. Never point a committed MCP command at a var that only exists in interactive shells. **Superseded form (2026-07, template-tools#144):** the command is now `"${HOME}/.local/bin/ast-mcp"` -- one binary both the laptop and the cloud installer already write -- not the project-relative `${CLAUDE_PROJECT_DIR:-.}/.ast-mcp/...`.
- **A design decision that isn't in the generator isn't a decision (2026-07, template-tools#144)**: RD5 was written down, but the canonical `mcp/manifest.json` still said `${AST_MCP_BIN}`, and `clai provision` regenerates `.mcp.json` on EVERY run -- so every run silently reverted the hand-corrected committed file back to the broken value. The doc and the code disagreed for weeks and the doc lost, quietly, on every provision. When a rule governs generated output, encode it where the generation happens (and add the regression test), not only in prose.
- **Scope precedence and approval decide which MCP server actually runs (2026-07, #99)**: Project `.mcp.json` and user `~/.claude.json` servers are matched **by name**; the highest-precedence source supplies the whole entry, and project outranks user. But an **unapproved** project entry is *skipped* in favor of user scope, and a fresh clone is never approved (the approving `.claude/settings.local.json` is gitignored; a checked-in `enableAllProjectMcpServers` is ignored in an untrusted folder). So a cloud sandbox runs the USER-scope server while an approved laptop runs the PROJECT one. Point both scopes at the SAME binary path, or you ship a config that works in exactly one of the two places -- and earns a permanent `[Conflicting scopes]` diagnostic.
- **`clai provision` is silent without `--report` (2026-07, #84)**: Every skip -- `not_a_project`, an absent agent config, a straggler-blocked skills dir -- exits 0 with no output. A sandbox that provisioned NOTHING looks exactly like one that provisioned everything. The unattended wrappers (`sandbox/provision.sh`) now always pass `--report`, because a session log is their only forensic trail.
- **CLAUDE.md is ingested verbatim -- comments are NOT stripped (2026-07, #127)**: Claude Code injects the entire global/user `CLAUDE.md` into model context as-is; `<!-- HTML comments -->` are not filtered -- they cost tokens and read as instruction-adjacent text every session. Keep centrally-placed instruction files 100% instruction content; put "generated, don't edit" provenance OUT of the file body (sibling marker / package README), never in an in-file comment.
- **`claude.ai > Settings > General > Instructions` is not shared with Claude Code and has no API (2026-07, #127)**: That personal-instructions field lives only in the claude.ai web app -- the Anthropic Messages API and Claude Code never see it, and there is no public/CLI endpoint to read or sync it (the web app's save call is internal, cookie-gated, unsupported). Cross-cutting agent instructions must be delivered another way: hence the repo-agnostic global `CLAUDE.md` placed by the sandbox setup stage. The claude.ai box and the repo file stay manually denormalized; there is no clean sync.
- **A test that drives cloud-detecting production code must strip the detector's inputs (2026-07, #127)**: `naatm-sandbox`'s smoketest calls `setup-core.sh`, whose new placement gates on `CLAUDE_CODE_REMOTE`/`HOME=/root`. Run inside a cloud sandbox, those ambient signals leak into every child invocation -- the "non-cloud no-op" case wrote the REAL `/etc/claude-code/CLAUDE.md`. Fix: `unset CLAUDE_CODE_REMOTE` at the top of the suite; each cloud case opts in explicitly with a scratch `CLAUDE_GLOBAL_ETC_DIR`. When a test exercises "am I in the cloud?" code, neutralize the detector or the test mutates the real host.
- **No safety-timer for PR-watch when webhooks deliver (2026-07, #151)**: The activity subscription already delivers Copilot reviews and CI failures as events; the only thing a webhook never sends is the merge/close transition -- and that is a human action you don't poll for. Arming a ~1h "safety check-in" for a watched PR is wasted quota. Rely on the subscription; do not schedule a timer to babysit a PR that is already event-driven.
- **Claude Code's Bash tool does not propagate `OTEL_*` to child shells (2026-07, smoketest_lmde_clai)**: clai injects the full OTel telemetry profile (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES=repo=...`, etc.) into every agent it launches, but a bash probe spawned by that agent's Bash tool sees NONE of it -- only ambient `CLAUDE_CODE_ENABLE_TELEMETRY`, inherited from the outer session, survives. So a probe cannot confirm the injection by reading its own inherited env; it must observe the injection at the source with `clai env` (which execs `env` through clai's launcher). Cost a real investigation to tell "clai isn't injecting" apart from "the measurement channel drops it." Lesson: when a subprocess env looks empty, suspect the channel, not the producer -- verify the producer directly.
- **A behavioral smoketest asserts observable end-state, not the tool that produced it (2026-07, smoketest_lmde_clai)**: laptop and cloud acquire the same world by different means -- `lmde acquire` on a laptop, `@nine-at-a-time-media/sandbox` in the cloud -- and the global CLAUDE.md is cloud-only (`setup-core.sh` skips it on a laptop). So the LMDE/CLAI smoketest branches on `CLAUDE_CODE_REMOTE` (L3 asserts the global CLAUDE.md in cloud / skips it on a laptop; cloudflare-disable and telemetry are laptop-only launch effects, auto-passed in cloud per boundary G1) and checks the convention paths regardless of which script placed them. One probe, two columns -- black-box keeps it version-agnostic too (passed against clai 0.5.5 on laptop and 0.6.0 in cloud, unchanged).

---

## Completed Tasks

### LMDE/CLAI Behavioral Smoketest (2026-07-12)

Black-box behavioral smoketest that confirms the LMDE/CLAI pairing behaves
correctly in both target environments. Implements `docs/design/LMDE-CLAI-BOUNDARY.DESIGN.md`'s
contract-by-convention as an observable check: it stands inside a real session
and interrogates end-state, stubbing nothing.

- [x] **`test/smoketest_lmde_clai/`**: `probe-lmde.sh` (L1-L4 -- clai on PATH,
  ast-mcp binary at `~/.local/bin`, global CLAUDE.md + "specificity" marker
  [cloud-only], `~/.local/bin` on PATH); `probe-clai.sh` (C1-C4 -- ast-mcp in
  the emitted `.mcp.json`, cloudflare MCP disabled [laptop], telemetry injection
  via `clai env`, skills placed in `.claude/skills`); `run-probes.sh` in-target
  executor (emits `OVERALL env=<env> failed=<n>`); `run-laptop.sh` driver
  (`clai claude -p` -> probes); `lib.sh` (PASS/FAIL/SKIP emit + cloud detection);
  `README.md` with the laptop/cloud matrix and caveats.
- [x] **Env-aware, black-box**: the global CLAUDE.md asserts in cloud / skips on
  laptop; cloudflare-disable + telemetry are laptop-only launch effects (cloud
  has no clai launcher, boundary G1). Same probe, two columns; version-agnostic.
- [x] **Verified green both environments**: laptop via real `clai claude -p`
  (clai 0.5.5) and cloud via a persisted claude.ai routine "LMDE/CLAI Smoketest"
  against the Default env (clai 0.6.0). `OVERALL failed=0` both; `L3` confirmed
  `/etc/claude-code/CLAUDE.md` carries the "specificity" marker in cloud.
- [ ] Follow-up (post-merge): repoint the cloud routine's source branch from
  `claude/lmde-clai-smoketest` to `master` once this lands.

### Leak Prevention and Stale Data Audit -- issue #131 (2026-07-11)

- [x] **Stale files cleanup**: Untracked legacy auto-save-list, semanticdb cache, and local `.DS_Store` files. Added `emacs/dot.emacs.d/semanticdb/` to `.gitignore`.
- [x] **Header scrubbing**: Scrubbed legacy hostnames from the `Author:` headers of `tds-pants.el` and `tds-bootstrap.el`.
- [x] **Soften phrasing**: Softened docstring phrasing in `tds-shell-mode.el`.
- [x] **Automated detector**: Added the `BLEED-HAZARD` warning category to `bin/clone-audit` (and tests in `test/smoketest_clone_audit.sh`) to prevent future checkins of stale files, legacy hostnames, or private network IPs.

### Universal Provisioning -- Global CLAUDE.md (2026-07-10)

- [x] **Central global CLAUDE.md (#127)**: Repo-agnostic global instruction file bundled in `@nine-at-a-time-media/sandbox` and placed by the setup stage -- cloud-only, `/etc/claude-code/CLAUDE.md` -> `/root/CLAUDE.md`, create-if-absent, `~` untouched, fail-open. Verified end-to-end against the packed tarball. Landed template-tools#151, published `@nine-at-a-time-media/sandbox@0.2.0`. Design: `docs/design/PROVISION.DESIGN.md` RD6. Follow-up: strip the in-file managed-header comment (token cost) -- separate issue.

### Cleanup & Maintenance (2026-07-04)

- [x] **Repository Gitignore Cleanup**: Added ignores for dynamic agent runtime caches/skills (`.agents/`, `.claude/skills/`, `.codex/`) to `.gitignore`, referencing `docs/design/PROVISION.DESIGN.md`.
- [x] **Issue Migration**: Successfully migrated 5 misfiled issues from `tds-utils` to `template-base` and `template-tools`.
- [x] **ci-magic Audit**: Audited `ci-magic` post-Phase 1 code and opened issue `template-tools#59` to track deficits (dead dependencies, unused plumbing, stale comments, table UX).
- [x] **ast-mcp Cache Audit**: Verified AST caching/rebuilding behavior on `ai-tools/main`.

### LMDE (Local Managed Developer Environment)

- [x] Task LMDE12: **NATS-in-kind: design.** Drafted `docs/design/LMDE-BACKPLANE.DESIGN.md`. Moves the message bus into the cluster with Caddy as the TLS edge and host bind-mounts for persistence. Incorporates Claude's design review feedback. PR #62.
- [x] Task LMDE13: **S3 Sync Monitor.** macOS menubar app (`bin/lmde-sync-monitor`) that uses `goldfish --check-s3` to alert when workplace repos are out of sync with their S3 mirrors. Includes `launchd` integration and custom status icons. PR #63.

### Goldfish

- [x] Task G10: **smoketest hermeticity: `resolve_orgs()` falls through to real `gh`.** Added a `--no-gh` flag to goldfish and updated the smoke runner to use it + `--no-filter`. PR #62.

### Terminal UX

- [x] Task T1: **Improve brand theme matching** -- added prefix and substring matching for terminal themes. PR #62.

### Style / Docs

- [x] Task SD1: **`prompts/`-wide SKILL.MARKDOWN.md compliance sweep.** Cleaned up smart quotes, em-dashes, and structural blank-line violations across all prompt files. PR #62.
- [x] Task T0: **Implement 'brand' command** -- single CLI to set Terminal theme (via AppleScript) and window/tmux title. Supports theme detection as first argument and stable session-level branding via tmux variables. PR #20.
- [x] Task EL1: **Migrate eldocker to eltainer.** Retired `eldocker` checkout, cloned user's `eltainer` fork, configured `upstream`, and updated Emacs `init.el` load-path.


- [x] Task 1: Secure log permissions in `log-hoarder` (restrict to owner read/write).
- [x] Task 1.1: Fix `tmux.conf` durable double/triple click selection in `root` table.
- [x] Task 2 (Design): Create `SEMANTIC-SEARCH.DESIGN.md` and scaffold Hexagonal architecture with `txtai` MVP.
- [x] Task 2 (Scaffolding): Implement domain models, ports, `TxtaiAdapter`, indexer, and searcher.
- [x] Task 2 (Design revision): Refine design with span/chunk model -- spans as semantic segments, chunks as embedding units, search groups by span.
- [x] Task 2a: Implement `Span` and `Chunk` domain models in `search/domain/models.py`. Added frozen dataclasses with validation, `Chunk.from_span()` factory, `index_key` property. 21 unit tests + 9 smoke tests against real session data. Also added `pyproject.toml` for log-hoarder and `__pycache__` to `.gitignore`. PR #10.
- [x] Task L1: Bring joy to the human via the tmux status bar and outer terminal title -- `tmux[<session>] <i>/<n> -- <pwd>/<cmd>` in the macOS title bar; `<idx>:<pwd>/<cmd><flag>` in the per-window status-bar labels. PR #19.
- [x] Task G1: Build `goldfish/` v1 -- at-a-glance recent-work report across GitHub repos and local clones. Hexagonal split: pure `core.py` (parsers, formatters, sort) with 33 unit tests, plus `shell.py` adapters wrapping `gh`/`git`/`ps`/`lsof`/`find`. Entry script fans probes across a `ThreadPoolExecutor` and renders a stderr progress bar. Hardcoded MVP config in `goldfish/config.json` (orgs allow-list, agent process whitelist, on-disk roots). PR #15.
- [x] Tasks G2/G3/G5/G6/G7 + Linux half of G4: goldfish post-MVP follow-ups. PR #18.
  - **G2** `--llm`: summarize each TODO_PLAN.md via `claude -p` (or `ollama run $GOLDFISH_OLLAMA_MODEL`) inside the per-row threadpool. Pure `first_meaningful_line` trims chatty output to <=200 chars.
  - **G3** clone-discovery cache: `$XDG_CACHE_HOME/goldfish/clones.json` (versioned, 24h TTL, validates each cached path still has `.git/`). `--refresh` forces rescan.
  - **G5** `--json`: stable JSON-array output with all columns, datetimes ISO-encoded, missing github/local as `null`.
  - **G6** `-v` / `--verbose`: lists every process whose cwd is inside a tracked repo (not just the agent whitelist), grouped by repo. Catches wrapper-launched agents.
  - **G7** `--include-org` / `--exclude-org`: repeatable filter flags, exclude wins over include.
  - **G4 (Linux scaffolding)**: hermetic `test/smoketest_goldfish/` bash suite, 6 scenarios, all green on Linux. macOS verification (`lsof` path) remains open as the G4 entry above.
- [x] Tasks G4 (macOS half) + G8: Verified goldfish on macOS (6/6 smoketests green, real-run JSON output sane). Added `bin/goldfish` symlink and `gf` alias in `macos/dot.alias`.
- [x] Task G9: **Repo-zoom mode (`gf <repo>`).** Added a positional repo-name arg that renders a one-repo vertical summary instead of the cross-repo table -- recent commits, open PR list with draft state, agents in cwd, full open-task list from TODO_PLAN.md, dirty/ahead state. Basename resolution against the clones cache (`gf tds-utils` finds `9atatimer/tds-utils`); pass `owner/name` to zoom an uncloned repo. New `ZoomData`/`CommitSummary`/`PRSummary` core types with 12 unit tests + `test/smoketest_goldfish/07_repo_zoom.sh`.

### Agent Workflow

- [x] Task AW1: **Default review-watch loop after `gh pr create`.** Rewrote `prompts/GITHUB.md`'s PR Activity Subscription section into a default-on review-watch loop. Two transports (MCP `subscribe_pr_activity` if loaded, else polling via `ScheduleWakeup`). On wake: `git switch <BRANCH>`, then `gh pr view --json state,mergedAt,reviews` (terminates on MERGED/CLOSED, catches overview-only reviews), then ALWAYS `gadmin github pending-comments` for inline (never short-circuit). After productive push: `gh pr edit <N> --add-reviewer @copilot` to trigger Copilot's next round (verified working; the standard REST request-reviewers API rejects the bot). Termination: merged/closed, 3 consecutive empty polls (~6 min quiescent at 2-min cadence), quality drop (push back once on nits then summary-exit), explicit human stop. PR https://github.com/9atatimer/tds-utils/pull/54. Companion `~/.claude/CLAUDE.md` updates: 240s wake-delay hard ceiling (90-180s default), "always disambiguate PRs by full URL" rule. Follow-up: Task GR1 above (bundle the on-wake dance into a `gadmin github review-state` verb) per https://github.com/9atatimer/tds-utils/issues/55.

### LMDE (Local Managed Developer Environment)

- [x] Task LMDE0: **Formalize LMDE concept and design Observability stack.** Created `lmde/LMDE.md` contract and drafted `docs/design/LMDE-OBSERVABILITY.DESIGN.md`. PR #44.
- [x] Task LMDE0.1: **Tech Radar Design.** Drafted `docs/design/WIP.TECH_RADAR.DESIGN.md` capturing the LMDE <-> Project-stack split.
- [x] Task LMDE1: **Implement Local Registry sync script.** Created `lmde/components/registry/sync.sh` and `images.txt` to mirror vetted, digest-pinned images to `localhost:5001`.
- [x] Task LMDE2: **Bootstrap Observability Stack.** Created `lmde/components/observability/setup.sh` and `kind-config.yaml` to deploy OTel, Prometheus, and Grafana with host-path persistence.
- [x] Task LMDE3: **Observability Smoke Tests.** Created `test/smoketest_lmde_observability/` to verify the end-to-end telemetry pipeline (OTLP -> Prometheus -> Grafana).
- [x] Task LMDE4: **Implement LMDE Tech Radar.** Created `prompts/SKILL.TECH_RADAR.md` based on the design doc, added the `CLAUDE.md` ingest hook, and backfilled "Adopted" and "Hold" tech.
- [x] Task LMDE5: **ingress-nginx host ingress for cluster vhosts.** Replaced the rejected istio approach -- added `lmde/components/networking/` (the Caddy `register_cluster_vhost` helper and a vendored ingress-nginx kind manifest), the `*.{cluster}.localhost` vhost scheme, and Grafana reachable at `grafana.lmde.localhost`. PR #49.
- [x] Task LMDE6: **Remove the legacy bash clai launcher.** `bin/clai` (bash) is superseded by the Python `clai` tool (uv-installed); removed it, its `test/smoketest_clai/` suite, and `CLAI.DESIGN.md`. PR #50.
