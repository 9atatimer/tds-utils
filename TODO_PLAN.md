# TODO_PLAN.md

This file tracks the status of development tasks, lessons learned, and completed work for the `tds-utils` repository.

## How to use this file
1. **Open Tasks**: Add new tasks here. Use checkboxes `[ ]` for pending and `[x]` for completed tasks.
2. **Lessons Learned**: After finishing a task or encountering a significant issue, document the insight here.
3. **Completed Tasks**: Move finished tasks from the "Open Tasks" section to this section.

---

## Open Tasks

### gadmin hardening (post-move follow-ups)

Pre-existing issues in the gadmin GitHub tools, surfaced by Copilot review on PR #25 when the tools were moved here from `Nine-At-A-Time-Media/template-tools/packages/naatm-admin`. The PR was intentionally a verbatim move; the fixes below are deferred to a follow-up so PR #25 stays scoped to "relocation only".

- [ ] Task GA1: **Stale path comments in moved headers.** `gadmin/admin/github` line 2 still says `# scripts/admin/github`; `gadmin/admin/github-octokit.mjs` line 3 says `* scripts/gadmin/github-octokit.mjs`; `gadmin/admin/github-gitapi.mjs` line 3 says `* scripts/gadmin/github-gitapi.mjs`. Update all three to the new tds-utils paths. (Copilot ID 3253832104.)
- [ ] Task GA2: **`pr-comments --detailed` parser breaks on pipes/newlines in comment bodies.** `gadmin/admin/github` `cmd_pr_comments` emits pipe-delimited records and a `while IFS='|' read` consumer; any `|` or newline inside `.body` corrupts subsequent records. Switch to NUL-delimited (`jq -j` + `\0` separators + `read -d ''`) or per-field-per-line records. (Copilot ID 3253832108.)
- [ ] Task GA3: **jq quote-injection from user-supplied workflow / job names.** `gadmin/admin/github` interpolates `$workflow` directly into a jq filter string in `cmd_actions_list_runs` (line ~552), and the same pattern with `${job_name,,}` / `${job_filter,,}` in `cmd_actions_get_job` (~648) and `cmd_actions_get_logs` (~719). A name containing `"`, `\`, or other jq metachars breaks the filter or matches unintendedly. Pass via `--arg name "$workflow"` and reference `$name` inside jq. (Copilot ID 3253832116.)
- [ ] Task GA4: **`listJobsForWorkflowRun` not paginated; runs with >100 jobs silently truncate.** `gadmin/admin/github-octokit.mjs` calls `octokit.rest.actions.listJobsForWorkflowRun` directly (no `.paginate`); `gadmin/admin/github-gitapi.mjs` calls `githubApi(...)` instead of `githubApiPaginate(...)` (~line 716). Switch both to paginated variants for consistency with `cmdActionsGetJob`. (Copilot ID 3253832121.)
- [ ] Task GA5: **`parseArgs` mishandles values that start with `--`.** Both `.mjs` tier scripts' `parseArgs` treat any value starting with `--` as a flag, so e.g. `--msg "--foo bar"` silently becomes a boolean and the value is re-parsed as the next flag. Either document the limitation or accept `--key=value` form. (Copilot ID 3253832126.)
- [ ] Task GA6: **`cmd_pending_comments` doesn't validate resolved repo/PR are non-empty.** Unlike `cmd_pr_comments` (lines 190–197), `cmd_pending_comments` in `gadmin/admin/github` doesn't re-check the output of `resolve_repo_and_pr` for empty values before calling `validate_pr_matches_branch` and the GitHub API, producing a confusing error instead of "missing required option". Mirror the validation block from `cmd_pr_comments`. (Copilot ID 3253832127.)
- [ ] Task GA7: **Dispatcher's `github-*` fallback exposes `gadmin octokit` / `gadmin gitapi` as top-level commands.** `gadmin/gadmin`'s `find_in_dir` tries `github-${command}[.sh|.mjs]` as a fallback, which makes `gadmin octokit pr-comments` and `gadmin gitapi pr-comments` work — and risks collision with future project extensions named `octokit` or `gitapi`. Either restrict the alias to `gadmin github octokit/gitapi`, or remove the github-* fallback entirely (canonical `gadmin github` already covers tier 1). (Copilot ID 3253832130.)

### Terminal UX

- [ ] Task T1: **Improve brand theme matching** — currently it does a literal case-insensitive match. If "Solarized Dark" is a theme, `brand solarized` fails. Add a fuzzy or substring match for theme names.

### UX / Interaction Quality (high-friction issues with the current proof-of-concept)

- [ ] Task U0: **Purge sampling terminology and code.** The `get_log_sample()` function in `search/cli/index.py`, the `sample_logs()` function in `log_brander`, `content_sample` field on `LogEntry`, and the `"text"` construction in `TxtaiAdapter.add_entries()` all embody a "sample a few lines to represent a session" approach that is fundamentally wrong for semantic search and confusing to maintain. Remove or rename: `content_sample` → remove from `LogEntry` (chunked pipeline replaces it), `get_log_sample()` → delete (Tasks 2b-2e replace it), `sample_logs()` in `log_brander` → rename to `extract_branding_context()` (brander legitimately needs a summary, but should not call it a "sample"). Clean up any references in comments and docstrings.
- [ ] Task U1: **Search latency — eliminate process-per-keystroke startup cost.** Every fzf `change:reload` spawns a new Python process that loads the txtai embedding model from disk. This is the dominant cause of dropped characters and sluggish response. Needs a long-running search process (daemon, UNIX socket, FIFO, or similar) so fzf reloads talk to a warm model. Design doc should specify the approach.
- [ ] Task U2: **Preview pane should show the matching region.** Currently `head -c 4000 {1}/*.log | head -80` shows the top of the file, which has no relationship to why it ranked high. Once chunk-level search (Tasks 2d-2f) produces byte offsets, update `log_search` output format and the ZLE widget's `--preview` command to extract the matching byte range from the source log. Depends on Tasks 2d-2f.
- [ ] Task U3: **Selecting a result opens multiple files in $PAGER.** The ZLE widget globs `*.log(N)` on the pane directory and passes all matches to `$PAGER`. A pane dir can accumulate multiple `.log` files from reuse across tmux sessions. Need to either: (a) resolve search results to a specific `.log` file (not just the pane dir), or (b) concatenate with clear separators, or (c) open only the file containing the matching byte range. Depends on chunk-level search output.
- [ ] Task U4: **Search result display lines are unreadable.** The fzf result list shows raw archive paths (`/Users/stumpf/.local/share/log-hoarder/archived/1/1/0`) which are meaningless to a human. Display should show: slug (if branded), tail 2-3 directory components of the working dir at span start, compact datetime, and optionally the tmux window name. The preview pane provides full context — the result line just needs to be scannable.

### Smoke Test & CLI (drives everything below — write tests first, then build until they pass)

- [x] Task S1: Create `log_search` CLI — the entry point for both the ZLE widget and the smoke test. Takes a query string, prints ranked results (session path, working dir, timestamp, preview). Lives in `bin/log_search` and delegates to the Python search pipeline.
- [x] Task S2: Create smoke test harness `test/smoketest_log_search/` — shell scripts following the grubsta pattern (`config.sh`, `run_all.sh`, numbered scenario scripts). Tests run against real `$TDS_LOG_DIR/archived/` data.
- [x] Task S3: Smoke test scenario — `01_index_archived_logs.sh` — run the indexer against real archived logs, assert exit 0 and index is non-empty. Setup for all subsequent tests.
- [x] Task S4: Smoke test scenario — `02_keyword_match.sh` — `log_search "ollama"` returns a result pointing to a session that contains "ollama" (sessions 2/1/0 and 3/0/0 both have ollama activity).
- [x] Task S5: Smoke test scenario — `03_semantic_match.sh` — `log_search "checking environment variables for a running service"` returns a result pointing to the launchctl/OLLAMA session (1/1/0) even though the query doesn't share exact keywords.
- [ ] Task S6 (future): Smoke test scenario — project-scoped search. `log_search "git clone in 9atatimer"` returns session 2/2/0 (which has `cd workplace/9atatimer && git clone`). Requires working dir context in embeddings.
- [ ] Task S7 (future): Smoke test scenario — cross-project filter. Same query scoped to a different project returns different/no results.
- [ ] Task S8 (future): Smoke test scenario — search across compressed and uncompressed logs returns consistent results.

### Shell Integration

- [x] Task Z1: Create ZLE widget for `ctrl-x s` — invokes `log_search`, pipes results through `fzf` for selection, displays matched log section in `$PAGER`. Plugin file `macos/dot.zsh_log_search`, sourced from `dot.zshrc`. PR #12.

### log-hoarder / tmux UX

- [ ] Task L2: **Adopt meaningful session names** — default numeric (`18`, `19`, `20`…) make `tmux ls` and the new title-string both worse than they need to be.
- [ ] Task L3: **Handle session-rename → log-path drift** — `tmux_logging.sh` bakes `#S` at pipe-pane time, so renaming a live session splits its logs across old and new dirs.

### Pipeline (implementation work driven by smoke tests above)

- [ ] Task 2b: Implement `Segmenter` — reads log text, detects span boundaries (prompt lines with cd, tool switches, idle gaps), returns `Span` objects with byte offsets. Pure domain logic in `search/domain/segmenter.py`. Should accept text, not file paths — keeps it pure for future compression abstraction.
- [ ] Task 2c: Implement `Chunker` — splits a span's text into embedding-sized `Chunk` objects with overlap. Pure domain logic in `search/domain/chunker.py`.
- [ ] Task 2d: Update `SearchIndexPort` and `TxtaiAdapter` — store chunk embeddings keyed by `session:span:chunk` with byte-offset metadata. Add `EmbeddingPort` to `ports.py`.
- [ ] Task 2e: Update indexer — replace `get_log_sample` with full pipeline: read log → segment into spans → chunk each span → embed → store. Move `indexer.py` into `search/`.
- [ ] Task 2f: Update searcher — query returns chunk hits, group by span, return ranked span references. Move `searcher.py` into `search/`.
- [ ] Task 3: Wire `log_search` CLI to the searcher. Get smoke tests S4 and S5 passing.
- [ ] Task 4: Integrate indexer into `tmux_shepherd.sh` cron mode.
- [ ] Task 5: Phase 2 — Implement `SqliteVecAdapter` + `OllamaAdapter` for lighter-weight alternative.
- [ ] Task 6 (future): Compressed log storage — implement compression in archive pipeline, update file-access abstraction, get smoke test S8 passing.

### Security / Credentials

- [ ] Task SEC1: **Rotate the GitHub Packages PAT in `~/.npmrc` and switch to a non-plaintext source.** Current state: a read-only PAT sits cleartext in `~/.npmrc` (`//npm.pkg.github.com/:_authToken=ghp_...`) and was emitted twice into a Claude transcript during a Mini Shai-Hulud audit (CVE-2026-45321, 2026-05-11). Replace with shell wrappers around `npm`/`pnpm`/`yarn`/`npx` that hydrate `${GITHUB_PACKAGES_TOKEN}` at call time. Preferred source: `gh auth token` (gh's own creds live in macOS keychain). Fallback: `security find-generic-password -s github-packages-pat -a 9atatimer -w`. The `.npmrc` line becomes `${GITHUB_PACKAGES_TOKEN}` so no secret on disk. Wrappers land in `bash/dot.bashrc.d/` (or `macos/` if zsh-only). Read-only scope limits blast radius but the token is functionally burned; rotate at revoke time.

---

## Lessons Learned

- **Securing Log Permissions**: Use `umask 077` at the start of logging and management scripts to ensure new directories and files are restricted to the owner. Perform a recursive `chmod -R u+rwX,go-rwx` on the log directory in management scripts like `tmux_shepherd.sh` to fix existing permissions without making non-executable files executable.
- **Hexagonal Architecture**: Decoupling the search index interface (`SearchIndexPort`) from the implementation (`TxtaiAdapter`) allows for an easy swap from a "heavy" framework like `txtai` to a lighter one like `sqlite-vec` later, while keeping the core logic intact.
- **Single Source of Truth (target state)**: The index will store only embeddings and metadata (session path, span ID, chunk index, byte offsets). The original log files are the sole content store. No raw text in the index, no sampling or truncation -- every byte of every log must be covered by embeddings. Note: the current MVP scaffolding still uses content sampling; Task 2a-2f replaces this with span-based chunked indexing.
- **Full Coverage Required**: A single session may span multiple projects and tasks. Sampling head/tail lines is useless for semantic search -- the indexer must segment into spans and chunk the entire file.
- **Spans vs Chunks**: Chunks are the unit of embedding (sized for the model's context window). Spans are the unit of retrieval (logically coherent stretches of activity). Search returns span references; chunks are an implementation detail of the index.
- **Byte Offsets Reference Uncompressed Content**: All byte offsets in `Span` and `Chunk` models reference the uncompressed log stream. This keeps the index format stable regardless of whether the underlying file is compressed or not. Log-reading code should go through a single file-access abstraction so compression can be added in one place later.
- **Frozen Dataclasses with Validation**: Using `@dataclass(frozen=True, slots=True)` with `__post_init__` validation catches invalid state at construction time. The `Chunk.from_span()` factory enforces that chunk byte ranges fall within their parent span — this is a domain invariant, not just a nice-to-have.
- **Real Log Format**: Log lines follow the pattern `HH:MM:SS user@host:dir % command`. Prompt lines with `% cd` are the primary span boundary signal. Logs range from 3KB (short sessions) to 8.8MB (long benchmarking runs). The segmenter will need to handle heavy non-printable/control character noise from terminal output (tab completion artifacts, ANSI remnants post-ansifilter).
- **Test Behavior, Not Implementation**: Domain models (dataclasses, validation, properties) are implementation details — testing them in isolation is change-detection, not bug-detection. Smoke tests should exercise the user-visible behavior: "I type a query, I get back the right session." Write that test first, then build until it passes. Unit tests for internal components only earn their keep if they test a behavioral contract that matters to the pipeline.
- **Smoke Tests Hit Real Systems**: A smoke test runs the real tool against real data and checks real output. Hardcoded fixtures pretending to be real data are just unit tests with extra steps. Smoke tests for log search run against `$TDS_LOG_DIR/archived/` and skip gracefully when unavailable.
- **`git status --porcelain=v1 -b` lies about fresh repos**: A repo with no commits prints `## No commits yet on <branch>`, not `## <branch>`. A naive `^##\s+(\S+)` branch regex captures `No`. Special-case the `No commits yet on ` prefix or every freshly-init'd repo gets mis-labeled. (Discovered while building goldfish.)
- **`/proc/<pid>/comm` is the binary basename, not `argv[0]`**: When the kernel does `execve`, it sets `comm` from the path of the executable, not what `argv[0]` says it is. Faking a renamed process for a test (e.g. a stand-in `claude`) requires `prctl(PR_SET_NAME, b"claude")` -- `os.execvp('bash', ['claude', ...])` doesn't work. Real-world flip side: an agent invoked through a wrapper script (e.g. `python3 launcher.py` that re-execs the real binary) presents `comm=python3` and slips past any name-based whitelist. Keep agent whitelists permissive, or match on cwd + open-fds instead of `comm`.
- **Terminal Branding via AppleScript/tmux**: Programmatically changing macOS Terminal themes requires `osascript` to talk to Terminal.app profiles. Combining this with `tmux set-option @brand` allows for a "dual-layer" branding where the theme is global to the tab but the title bar dynamically updates as you switch tmux windows. Conditional tmux formatting (`#{?@brand...}`) can then be used to hide the CWD prefix only when a brand is active.

---

## Completed Tasks

### Terminal UX

- [x] Task T0: **Implement 'brand' command** — single CLI to set Terminal theme (via AppleScript) and window/tmux title. Supports theme detection as first argument and stable session-level branding via tmux variables. PR #20.

- [x] Task 1: Secure log permissions in `log-hoarder` (restrict to owner read/write).
- [x] Task 1.1: Fix `tmux.conf` durable double/triple click selection in `root` table.
- [x] Task 2 (Design): Create `SEMANTIC-SEARCH.DESIGN.md` and scaffold Hexagonal architecture with `txtai` MVP.
- [x] Task 2 (Scaffolding): Implement domain models, ports, `TxtaiAdapter`, indexer, and searcher.
- [x] Task 2 (Design revision): Refine design with span/chunk model — spans as semantic segments, chunks as embedding units, search groups by span.
- [x] Task 2a: Implement `Span` and `Chunk` domain models in `search/domain/models.py`. Added frozen dataclasses with validation, `Chunk.from_span()` factory, `index_key` property. 21 unit tests + 9 smoke tests against real session data. Also added `pyproject.toml` for log-hoarder and `__pycache__` to `.gitignore`. PR #10.
- [x] Task L1: Bring joy to the human via the tmux status bar and outer terminal title — `tmux[<session>] <i>/<n> -- <pwd>/<cmd>` in the macOS title bar; `<idx>:<pwd>/<cmd><flag>` in the per-window status-bar labels. PR #19.
- [x] Task G1: Build `goldfish/` v1 -- at-a-glance recent-work report across GitHub repos and local clones. Hexagonal split: pure `core.py` (parsers, formatters, sort) with 33 unit tests, plus `shell.py` adapters wrapping `gh`/`git`/`ps`/`lsof`/`find`. Entry script fans probes across a `ThreadPoolExecutor` and renders a stderr progress bar. Hardcoded MVP config in `goldfish/config.json` (orgs allow-list, agent process whitelist, on-disk roots). PR #15.
- [x] Tasks G2/G3/G5/G6/G7 + Linux half of G4: goldfish post-MVP follow-ups. PR #18.
  - **G2** `--llm`: summarize each TODO_PLAN.md via `claude -p` (or `ollama run $GOLDFISH_OLLAMA_MODEL`) inside the per-row threadpool. Pure `first_meaningful_line` trims chatty output to <=200 chars.
  - **G3** clone-discovery cache: `$XDG_CACHE_HOME/goldfish/clones.json` (versioned, 24h TTL, validates each cached path still has `.git/`). `--refresh` forces rescan.
  - **G5** `--json`: stable JSON-array output with all columns, datetimes ISO-encoded, missing github/local as `null`.
  - **G6** `-v` / `--verbose`: lists every process whose cwd is inside a tracked repo (not just the agent whitelist), grouped by repo. Catches wrapper-launched agents.
  - **G7** `--include-org` / `--exclude-org`: repeatable filter flags, exclude wins over include.
  - **G4 (Linux scaffolding)**: hermetic `test/smoketest_goldfish/` bash suite, 6 scenarios, all green on Linux. macOS verification (`lsof` path) remains open as the G4 entry above.
- [x] Tasks G4 (macOS half) + G8: Verified goldfish on macOS (6/6 smoketests green, real-run JSON output sane). Added `bin/goldfish` symlink and `gf` alias in `macos/dot.alias`.
