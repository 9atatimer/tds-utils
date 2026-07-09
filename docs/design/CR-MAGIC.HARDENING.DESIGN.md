# CR-MAGIC: Design Review & Hardening Proposal

> **Status:** DRAFT
> **Date:** 2026-07-09
> **Authors:** Todd Stumpf, Claude
> **Depends on:** cr-magic `docs/design/CR-MAGIC.ARCHITECTURE.md` (the system being reviewed)

---

## Overview

This is a design-review and hardening proposal for **CR-MAGIC**, the tool that
orchestrates review cycles between a CLI coding agent (Claude Code / Gemini CLI)
and GitHub Copilot. The architecture is sound -- a pure FSM behind ports/adapters
-- but the implementation has a wide gap between its *documented* surface and its
*actual* behavior: the review-convergence logic does not converge on real Copilot
output, most CLI commands are stubs, and the persistence/recovery machinery is
built but never invoked. This doc catalogs the gaps and proposes a prioritized
plan to make the tool do what its own design doc already promises.

**Scope note -- two codebases.** There are currently *two* divergent copies of
CR-MAGIC:

| Copy | Path | State |
|------|------|-------|
| Standalone | `nine-at-a-time-media/cr-magic` -> `packages/cr-magic/` | Older. CLI stubs, no telemetry. Audited in detail here. |
| Canonical  | `nine-at-a-time-media/template-tools` -> `packages/crmagic/` | Newer. Has OTEL/bootstrap. Target of open issues #79/#80. |

Resolving this fork is itself a proposal item (see Design section G). Unless noted,
findings below were verified against the **standalone** copy; the classification,
promotion, recovery, and trust-boundary findings apply to both.

---

## Goals

1. **Convergence actually converges** -- On a real Copilot-reviewed PR, a run
   reaches `CONVERGED` via `COMMENTS_TRIVIAL_ONLY`/`NO_COMMENTS_TIMEOUT` when the
   agent has resolved substantive comments, rather than always churning to
   `MAX_ITERATIONS -> ESCALATE`.
2. **Documented CLI = working CLI** -- Every command listed in the README/arch doc
   (`status`, `cancel`, `gc`, `bug-report`, `logs`) performs its function or is
   removed from the docs. No `[Not yet implemented]` reachable from a documented path.
3. **Recovery is real** -- A crashed run can be resumed from persisted state (a
   `resume` path exists and is tested), justifying the `PromotionProgress` /
   schema-version machinery already present.
4. **Trust boundary is explicit** -- No executable (`gadmin`) is resolved from the
   current working directory or from a repo under review; comment text reaching the
   agent is treated as data, and the agent runs under an explicit tool allowlist.
5. **Tests exercise behavior, not names** -- The "System Invariant" tests fail if
   the invariant is actually violated (path traversal, cursor advance, shell
   safety), and the real adapters -- not only fakes -- are covered on the classify
   and promotion paths.
6. **One home** -- Exactly one canonical CR-MAGIC package; the other is archived or
   reduced to a pointer.

---

## Non-Goals

- **Rewriting the FSM** -- The pure `(State, Event) -> (State, Action)` core is the
  strongest part of the codebase and should be preserved as-is.
- **Adding new user-facing features** -- Dashboard mode, Slack, notifications, and
  the data-lake export stay deferred (they are already Future Considerations in the
  architecture doc). This proposal is about making the *existing* promised surface
  correct.
- **Changing the fork-first review strategy** -- The `9atatimer` fork ->
  `GoodPlates` promotion model is a product decision, not under review here.

---

## Architecture Overview

The layering is unchanged from the existing architecture doc. This proposal only
touches the shaded seams -- the adapter implementations and the CLI wiring -- not
the FSM core.

```
+-----------------------------------------------------------------------+
|  CLI LAYER (click)                                                     |
|    start [OK]   status/cancel/gc/bug-report/logs  [STUBS -> Goal 2]    |
|    (no) resume                                    [MISSING -> Goal 3]  |
+---------------------------------+-------------------------------------+
                                  |
+---------------------------------v-------------------------------------+
|  ORCHESTRATION (ReviewOrchestrator)                                   |
|    pure FSM  [OK, keep]                                               |
|    poll/classify driver     [converges wrong -> Goal 1]              |
|    signal handling          [flag-only, agent not interrupted]       |
+---------------------------------+-------------------------------------+
                                  |
+---------------------------------v-------------------------------------+
|  ADAPTERS                                                             |
|    GitHubCommentClient  [placeholder parse + broken classify -> G1]  |
|    GitHubPRClient        [promotion head ref wrong -> Goal 1]        |
|    FilesystemWorkspaceStore [create_workspace is a no-op TODO]       |
|    AgentRunner           [--continue arg contract unverified]        |
|    gadmin resolution     [walks cwd -> trust boundary -> Goal 4]     |
+-----------------------------------------------------------------------+
```

---

## Design

The proposal is organized as lettered work-streams A-G, each with a problem
statement (what the code does today), the fix, and priority. Priority key:
**P0** = tool is functionally wrong without it; **P1** = correctness/security gap;
**P2** = quality/efficiency.

### A. Comment classification & convergence (P0)

#### Responsibilities

| Concern | Today | Proposed |
|---------|-------|----------|
| Fetch | `get_pending_comments` splits gadmin stdout on `"---"`, sets `id = "ext-" + str(hash(body))`, `created_at = datetime.now()`, ignores `since`. | Parse gadmin's structured (JSON) output into `Comment` with stable GitHub comment IDs, real timestamps, `path`/`line`. |
| Actionability | `Comment.is_actionable` is computed (`"FIXME"/"TODO"/"?"`) then **discarded**; `classify_comments` re-derives from substring match on prefixes (`"bug:"`, `"nit:"`). | Single source of truth. Classify with the config's regex patterns applied to normalized text, exactly as the arch doc specifies. |
| Regex vs substring | `lint_patterns` are regex in config but matched with Python `in` (substring). `unused (variable\|import\|parameter)` never matches literally. | Use `re.search` over lowercased/whitespace-collapsed body, per the arch doc's stated contract. |
| Unknown bucket | `unknown_count` is **always 0**; the `else` branch increments `actionable`. Copilot does not prefix comments, so almost everything is "actionable" forever. | Real three-way split; unknown -> actionable is a deliberate, counted decision, not an accident. |
| Cursor | `last_comment_cursor` is **never written**. Invariant #10 is unimplemented. | Advance the cursor after each classify+act cycle; pass it as `since` to skip already-handled comments. |
| Re-review | Copilot review is requested once at setup and once at promotion, never on iterations. | Re-request Copilot (`--add-reviewer @copilot`) after each agent push, matching `prompts/GITHUB.md`'s documented loop. |

**Why this is P0:** the combination of (never advancing the cursor) + (never
re-requesting Copilot) + (everything classified actionable) means a real run
re-reads the same unresolved threads every iteration and marches straight to
`MAX_ITERATIONS -> ESCALATE`. Convergence only happens when a PR has *zero*
comments. The tool's headline behavior does not work on its intended input.

### B. CLI completeness & recovery (P0/P1)

`status`, `cancel`, `gc`, `bug-report`, and `logs` all print
`[Not yet implemented]`, yet the store already implements the hard parts
(`list_active_runs`, `detect_orphaned_locks`, `load_run`) and nothing calls them.
There is **no `resume` command at all**, so `PromotionProgress`, `schema_version`,
`_migrate_schema`, and "persist before side-effects" are dead machinery.

| Command | Backing code that already exists | Action |
|---------|----------------------------------|--------|
| `status` | `list_active_runs()`, `load_run()` | Wire it up (P0 -- it is the only way to see a stuck run). |
| `cancel` | flock + `SIGNAL_RECEIVED` transition | Implement; without it a stuck lock can only be cleared by killing PIDs / `rm`-ing lock files. |
| `gc` | `detect_orphaned_locks()` | Wire it up; add the documented `--older-than`/`--state`/`--orphans`/`--dry-run` semantics. |
| `bug-report` / `logs` | (agent output not persisted) | Persist per-run `run.log` (see D7) then bundle it. |
| `resume` (new) | `load_run()` + roll-forward promotion | Add a command that reloads a persisted `RunState` and continues the loop. This is the payoff for all the persistence work. |

Alternatively, if some of these are genuinely out of scope, **delete them from the
README and arch doc** so the documented surface is honest (Goal 2).

### C. Promotion correctness (P1)

`_action_do_promotion` step 3 creates the primary PR with
`create_draft_pr(org=primary_org, repo, branch=<branch>)`, which runs
`gh pr create --head <branch> --repo <primary>/<repo>`. For a cross-fork PR the
head must be namespaced: `--head <fork_org>:<branch>`. The correctly-formed helper
`GitHubPRClient.promote_pr` (which *does* use `--head f"{fork.org}:{fork.branch}"`)
exists but is **never called**. Proposal: route promotion through a single correct
method and delete the dead one, or fix the inline path's head ref. Add an
integration test that asserts the `--head` argument is fork-namespaced.

### D. Adapter & type hygiene (P1/P2)

| # | Problem | Fix |
|---|---------|-----|
| D1 | `create_workspace` is a `# TODO: Actually clone` no-op; orchestration clones separately via raw `subprocess`, bypassing the port. The port docstring claims it clones. | Move the clone into the adapter (honor the port contract) or change the contract; don't have both. |
| D2 | Two parallel type hierarchies: `ports.PR/PRMetadata/Comment` differ in shape from `domain.PR/PRMetadata/Comment` with the same names. Adapters return domain types; Protocols are annotated with ports types. | Collapse to one set. `mypy --strict` (the project's own gate) should be flagging this. |
| D3 | `BranchResolver.resolve` returns `Any` with function-local imports. | Return `BranchRef`; violates the repo's own "Never use `Any`" rule. |
| D4 | Agent resume uses `--continue <session_id>`. Claude Code's `--continue` takes no argument (`--resume <id>` takes the id); Gemini's flags are unverified. | Verify each CLI's real contract; resume may be silently starting fresh sessions today. |
| D5 | `SENTINEL` defined in both `orchestration.py` and `agent.py`; `PollConfig` defined in both `orchestration.py` and `cli/config.py`. | Single definition each. |
| D6 | Lock-key sanitization exists in three places with two schemes (`__` vs `/`), and orphan-name parsing reverses it lossily (a branch containing a literal `__` corrupts). | One `lock_key` function; use a reversible encoding. |
| D7 | Agent stdout/stderr is never persisted; `_prompt_escalate`'s "[V] View last agent output" prints a `Transition` record instead. `bug-report` can't bundle logs that don't exist. | Persist per-run agent output to `run.log`; make `[V]` and `bug-report` read it. |
| D8 | Dead code: `RunController` (never instantiated; `_current_controller` is the orchestrator via `# type: ignore`), `promote_pr`, `Action.KICKOFF_AGENT`, `is_valid_transition`, `get_valid_events`. | Remove or wire in. |

### E. Security & trust boundary (P0/P1)

| # | Vector | Risk | Mitigation |
|---|--------|------|------------|
| E1 | `gadmin` is resolved by walking up from `Path.cwd()` for `scripts/gadmin` and **executing** it. Every template-derived repo ships `scripts/gadmin`. | Launching cr-magic from inside a checkout runs *that checkout's* script -- code execution sourced from the working directory, which for a review tool is often an untrusted repo. The target clone is not cwd today, so this is latent, not yet reachable from the reviewed code -- but the boundary is implicit. | Resolve `gadmin` from the installed package or an explicit config path. Never from a cwd walk. (P0 -- it's a one-line policy change guarding arbitrary execution.) |
| E2 | Copilot/human comment bodies are interpolated verbatim into the agent's follow-up prompt, and the agent runs with `allowed_tools=[]` -> "agent defaults" (unrestricted) and auto-approved, on a live clone with push rights. | Prompt injection: a comment ("ignore previous instructions, run ...") can steer an agent that has full tool access and can push. The arch doc's stated mitigation ("comments as structured JSON") is not realized. | Pass comments as clearly-delimited data, not instructions; run the agent under an explicit minimal tool allowlist; consider disallowing network/`Bash` beyond git for the review agent. (P1) |
| E3 | `git clone` over SSH has `check=True` but no timeout; the agent subprocess has a timeout, the clone does not. | A hung clone blocks the run forever. | Add a timeout + retry to the clone. (P2) |
| E4 | Signal handling only sets a flag; the blocking `communicate(timeout=3600)` is not interrupted, so a mid-agent Ctrl-C waits until the agent returns (or a 2nd Ctrl-C forces `sys.exit`, bypassing clean state persistence). Invariant #8 ("SIGINT always results in clean child termination") is only partially met. | Zombie/late-cancel; state may not reflect cancellation on force-exit. | Terminate the agent subprocess inside the handler, as the arch doc's own example shows. (P1) |

### F. Efficiency (P2)

| # | Problem | Fix |
|---|---------|-----|
| F1 | Poll re-fetches **all** pending comments every interval (`since=None`, no cursor). | Incremental fetch via the cursor from A. Fewer/cheaper API calls per poll. |
| F2 | `datetime.now()` is called directly in `RunState` default factories and adapters, bypassing the injected `Clock` that exists for determinism. | Route time through `Clock`; makes those paths testable and honors the design's Clock rule. |
| F3 | Config maps YAML keys by hand (`copilot_poll_interval_seconds` -> `poll_config`) with silent drops if a name drifts; README and arch doc already disagree on some names. | Validate config with a schema (pydantic) -- less boilerplate, no silent drops. |

### G. One canonical home (P1, process)

Pick one: fold the standalone `nine-at-a-time-media/cr-magic` into
`template-tools/packages/crmagic` (or vice-versa), archive the loser, and update
the arch doc's install line (which currently points at the standalone repo while
the open issues and "new home repo" language point at template-tools). Two copies
guarantee that fixes land in one and rot in the other. Also: this standalone repo
carries `docs/design/DESIGN.LOCALDEV.md`, a ghost doc about grubsta/iommaps
localdev unrelated to cr-magic -- the exact fork-ghost pattern tracked in
`template-base#38`. Remove it here.

---

## State Machine

**No change proposed.** The FSM is correct and well-tested at the transition level.
The one observation is a cosmetic dead-end: `GOODPLATES_ROUND --AGENT_EXITED-->
DONE` carries a `PROMPT_HUMAN` action, but `DONE` is terminal so the main loop
exits before the prompt is ever shown. Either drop the action or add a real
post-promotion prompt. Recorded here so it is not mistaken for a bug during the A-F
work.

---

## Data Model

No schema change is required for this proposal; the existing `RunState` (schema v2)
already carries every field the recovery work needs (`last_comment_cursor`,
`poll_start_time`, `promotion`, `retry_count`). The work is to **use** them:

```
RunState (already persisted to runs/<id>/run.json)
+-- last_comment_cursor   <- WRITE IT (work-stream A); today always None
+-- promotion             <- READ IT on resume (work-stream B); today write-only
+-- transitions[]         <- keep; but also persist raw agent output to run.log (D7)
```

---

## Security Considerations

- **Executable resolution (E1)** -- `gadmin` must come from the installed package or
  explicit config, never a cwd/repo walk. Highest-leverage security fix.
- **Prompt injection + tool scope (E2)** -- Treat comment text as data; give the
  review agent an explicit minimal tool allowlist rather than "all tools,
  auto-approved," since it runs on a clone it can push.
- **Tainted input (holds today)** -- All `subprocess` calls use argv lists, no
  `shell=True`; branch/PR strings are not shell-interpolated. Invariant #4 is met at
  the shell layer -- keep it that way in any new code.
- **Secrets scaffolding** -- The standalone repo ships extensive `.env*` /
  `.env.crypt*` / terraform / supabase scaffolding around what is a local CLI tool;
  reconcile with the "one home" decision (G) so secret-bearing infra doesn't
  propagate to forks that only need the CLI.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Preserve the FSM | Keep `(State,Event)->(State,Action)` untouched | It is correct, pure, and the best-tested part; risk is all in the adapters. |
| Fix vs document CLI stubs | Implement `status`/`cancel`/`gc`/`resume`; the backing code already exists | Cheaper to wire existing store methods than to keep lying in the docs; `resume` unlocks the sunk-cost recovery machinery. |
| Classification source of truth | One regex-based classifier over normalized text | Matches the arch doc's stated contract; eliminates the dead `is_actionable` field and the substring/regex mismatch. |
| gadmin resolution | Package/config path only | Removes a cwd-sourced arbitrary-execution boundary for a tool whose job is to run on untrusted code. |
| One package | Consolidate to a single canonical `crmagic` | Two divergent copies is the root cause of drift and ghost bugs. |

---

## Open Questions

1. **Which copy is canonical?** The arch doc installs from the standalone repo; the
   issues live in `template-tools/packages/crmagic` and call it the "new home." Which
   one survives (G)?
2. **What is the real gadmin output format?** The parser is a `"---"` split
   placeholder. Does `gadmin github pending-comments` emit JSON we can parse to
   stable IDs? (Determines the shape of work-stream A.)
3. **Agent CLI resume contract** -- Does Claude Code want `--resume <id>` (not
   `--continue <id>`)? Does Gemini support `--output-format json` and session
   continuation at all? (Determines D4.)
4. **Should the review agent be sandboxed** beyond a tool allowlist (e.g., no
   network, git-only Bash), given it runs on code it can push? (E2 scope.)
5. **Convergence definition** -- Once classification works, is "no *actionable*
   comments after min-wait" the right convergence bar, or should the agent also have
   to explicitly resolve threads?

---

## Rejections

- **Rewrite as an event-driven/async daemon** -- Rejected: the arch doc's "no
  daemon; lives in a terminal" non-goal stands, and the synchronous loop is fine
  once the adapters are correct.
- **Auto-clear orphaned locks** -- Rejected: the design deliberately surfaces
  orphans to a human (`gc --orphans`) rather than auto-clearing; keep that.
- **Distributed rollback for promotion** -- Rejected (already, in the arch doc):
  roll-forward + persisted `PromotionProgress` is the chosen model; this proposal
  just asks that resume actually *reads* that progress.
- **LLM-based comment classification** -- Rejected for now: regex over normalized
  text is cheaper, deterministic, and testable; revisit only if regex proves too
  blunt against real Copilot phrasing.

---

## Future Considerations

- **Conformance table in the arch doc** -- Add a "design vs implemented" column so
  future readers don't trust unbuilt features (regex classify, cursor, resume,
  rate-limit handling are all described as if present). Flip the arch doc's status
  from DRAFT to reflect what is actually IMPLEMENTED once A-F land.
- **Final verification step** -- The arch doc already defers an optional
  `agent.validate_workspace()` (run tests/lint before promoting) to catch "converged
  but broken." Worth doing right after A, since a broken-but-quiet convergence is
  exactly what today's classifier produces.
- **Deferred features** -- Dashboard/tmux, macOS notifications, Slack, data-lake
  export remain out of scope until the core loop is trustworthy.

---

## Related Documents

- `nine-at-a-time-media/cr-magic` `docs/design/CR-MAGIC.ARCHITECTURE.md` -- the
  system under review; this proposal is a hardening pass against it.
- `template-tools#79` -- OTEL repo label is the workspace clone path (canonical copy).
- `template-tools#80` -- doubled `_USD` suffix in exported cost metric.
- `template-tools#83` -- guidelines describe a Python-only monorepo; now polyglot.
- `template-tools#58` -- no PR template for agent/human-authored PRs.
- `template-base#38` -- fork-ghost design docs propagate via the template seed
  (this repo's `DESIGN.LOCALDEV.md` is an instance).
- `prompts/SKILL.DESIGN.md`, `docs/design/TEMPLATE.md` -- authoring conventions this
  doc follows.
