# TODO_PLAN.md

> **Updated:** 2026-11-14

## How to use this file

Strategy only: what is in flight, in what order, and what blocks it. Every
unit of work is a file under `tasks/` (`ls tasks/` is the index); the
todo-plan skill owns the schema. Completed work lives in git history and
`tasks/done/`. Branch, commit and review rules are in `AGENT.md`.

## Now

- Instruction-file cut: tds-utils Issue#798 (`AGENT.global.md` is 746
  lines and loads Claude-only rules into every agent) and Issue#799
  (`AGENT.md` is over the Codex 32 KiB limit; this file was 126 KB), in
  progress on tds-utils PR#807. Issue#289 (migrate this file into
  `tasks/`) closes with it.
- Chores (`docs/design/CHORES.DESIGN.md`): built through task-013. Open:
  task-016 (due-detection edge cases), task-018 (owner decisions on
  built-but-not-designed rows, Issue#286), task-017, task-019, then
  task-014 (as-built at release, then the retrospective, the owner's).
- tmux-herd (`docs/design/TMUX-HERD.DESIGN.md`): task-020, build
  `bin/tmux-herd`. Its blocker, log-hoarder keying on `#{session_id}`
  (Issue#307), shipped in PR#310.
- Dynomark (`docs/design/DYNOMARK.DESIGN.md`; MVP merged, PR#535): task-054
  (owner rulings on the drift, Issue#538-Issue#543; Issue#540 loses data),
  task-055 (body amendment, Issue#544), then task-027 (the MVP acceptance
  run on the mbp). The retrospective waits on all three.
- OCR on Demand and Ollama Gateway (shipped 2026-10-13; as-built in
  `docs/arch/`): owner rulings on Issue#453, Issue#454, Issue#455 and the
  Markdown question under Blockers, then task-053 (fleet rollout), then
  task-046 (bring-up remainder on the laptop). Also Issue#442 and
  Issue#456.
- Architectural Adherence (`docs/design/DESIGN.ARCH-ADHERENCE.md`,
  `ARCHITECTURE.ARCH-ADHERENCE.md`; epic Issue#588): the engine gates this
  repository and the hosted judge is bound in CI. Open: the rollout
  (Issue#601: GammaGo, tds-internal, consumers), task-071 (explanations),
  task-072 (runbook and as-built), the drift bugs task-073 to task-079.
  Waiting on the owner, no task until ruled: Issue#678, Issue#679,
  Issue#680, Issue#683, Issue#690, Issue#691, Issue#712, Issue#713,
  Issue#719, Issue#720. Spec'd but not built: Issue#687, Issue#688.
  Issue#728 and Issue#729 are closed; the eval floor still runs in no CI
  job (Issue#622).
- Everything else open is its own file: LMDE (task-084 to task-090),
  log-hoarder search (task-091, task-092), sandbox lifecycle (task-094),
  and the standalone items task-081 to task-083, task-093, task-095.

## Blockers

- 2026-10-24: `lmde/TECH_RADAR.md` lacks a row for the Claude CLI as an
  explanation adapter (Issue#599, for task-071), and rows for Textual,
  PyYAML, rumps and Click (Issue#288). The file is human-maintained.
  Unblock: the owner lands the rows or refuses a ring.
- 2026-10-24: the `adherence-ledger` bucket is tds-internal Issue#276 (a
  human applies); until then the `ci` stage uses the file cache and says so.
- 2026-09-17: the chores retrospective waits on `bin/tds-release` and the
  chores tasks above; only the owner lands it.
- 2026-09-27: task-027 needs the mbp (real Chrome profile, native-messaging
  manifest, Ollama, launchd); no cloud session can run it. Run the daemon
  under a uv, python.org or Homebrew Python: the macOS system Python cannot
  load `sqlite-vec`.
- 2026-10-13: OCR on Demand and Markdown. `ocr` never selects Markdown, but
  G4's exclusion class does not exclude it, so every summary lists changed
  `.md` files as "not reviewed" and a Markdown-only PR fails
  `reviewed-nothing` (`lib/ocr-review/verdict.mjs`). Designed behavior.
  Unblock: the owner decides whether Markdown joins the exclusion class (a
  Key Decisions row in `OCR-ON-DEMAND.DESIGN.md`).
- 2026-10-16 and 2026-10-13: the Dynomark, OLLAMA-GATEWAY and OCR-ON-DEMAND
  retrospectives wait on their drift issues and task-027 and task-046; only
  the owner lands them.

## Lessons Learned (unsettled)

### Host-scoped design meets profile-scoped transport

about: wip

Dynomark's design makes HostRole per host, but native messaging connects per
browser profile, so the code chose a profile silently (Issue#419). Ruled
2026-10-16: bind on first hello, `dynomark-daemon rebind`, re-read the role
on every request (revisit Issue#527); a connection's cached role is never
trusted (`url.vet` answered a demoted writer, PR#535). At task-027 this goes
to `docs/arch/` for Dynomark.

### A ledger or guard that outlives a process needs its state table first

about: wip

Chores task-015 needed eleven Codex rounds because nobody had tabulated
record status x ledgered x in-window x kind x billing x budget against every
writer and write order. Dynomark's background-tab guard did the same: its
DNR rules and the tab record had different lifetimes, and giving both
`storage.session` deleted a heuristic. Proposal for the coding skill, owner
to land in Skills: a pre-code step that tabulates each piece of state's
lifetime and every writer's interleaving.

### Fake-driven CLI tests never exercised the composition root

about: wip

Every chores CliRunner test injected `obj=Deps(...)`, so `ctx.ensure_object`
pre-filling was invisible until the first real run. One test now drives the
CLI with no injected deps (`tests/unit/test_wiring.py`). Unsettled: whether
testing-python requires one such test per CLI.

### Fakes passed what the real dependency refused

about: wip

Three times in two components (ollama-gateway PR#440; the adherence
`github_reviews` adapter, twice) a green suite hid a defect that only the
real dependency, or a fake that accepted and ignored an argument, showed.
Proposed as Skills Issue#180: the fake records every argument the contract
names, the contract suite runs against fake and adapter alike, and one smoke
against the real dependency runs per adapter before its first merge. Moves to
`skill:testing` when that lands.

### Two sessions fixed one issue in parallel

about: wip

Issue#642 was fixed twice (PR#649, PR#655) and omp hooks were rewritten in
opposite directions (PR#757, PR#759): a comment with a patch does not claim
an issue, and an open PR on the same files is a conflict to resolve with the
owner, not to flag. Proposal for the github-workflow skill: before changing
a file, list the open PRs that touch it; self-assign or comment "taking
this" first.
