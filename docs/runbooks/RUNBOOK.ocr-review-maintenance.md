# RUNBOOK: changing OCR on Demand (workflow and tooling)

For whoever changes the `/ocr` review machinery itself. Using it (adopt,
seed, trigger, read a result) is `docs/ocr-review.md`. Design:
`docs/design/OCR-ON-DEMAND.DESIGN.md`, APPROVED and frozen; its Key
Decisions log is where later rulings live. Umbrella issue: Issue#363.

## Where things live

| Piece | Path | Notes |
|---|---|---|
| Reusable workflow | `.github/workflows/ocr-review.yml` | Thin YAML: three jobs (authorize, review, report), each step calling `bin/ocr-review <step>` |
| Step commands | `bin/ocr-review` | The composition root: env in, GitHub/git/op/fetch calls, step outputs out. Exports every `run*` flow and `gitIn` for tests |
| Decisions | `lib/ocr-review/*.mjs` | Pure: authorize, gateway probe classification, verdict, record and summary, host tools, reactions, stats |
| Caller template | `docs/ocr-review-caller.yml` | Copied verbatim into adopting repos; two SHAs pin it |
| Seeder, stats | `bin/seed-ocr-review`, `bin/ocr-review-stats` | Human-run; `status` reports each adopter's pin |
| Tests | `test/ocr_review_*.test.mjs`, `test/smoketest_ocr_review.sh`, `test/smoketest_seed_ocr_review.sh` | The smoketest is the list of node suites; a new suite is added there |
| Runner image | tds-internal `services/ci-runner-pool/Dockerfile` | The pool's host tools (git, gnupg, unzip, a pinned and verified `op`); its `test/wiring.test.ts` lists them |
| Gateway | `lmde/components/ollama-gateway/`, `lmde/components/proxy-layer/`; tds-internal `ops/terraform/ollama-gateway/` | The deadline status (507) and Host rewrite live in the route |

## Invariants a change must keep

Each is asserted by `test/ocr_review_workflow.test.mjs` or the io tests;
a change that needs to break one is a design change, not a fix.

- The authorize and report jobs reference no secret. Only the review job
  sees `OLLAMA_GATEWAY_OP_SA_TOKEN`, passed by name, never
  `secrets: inherit`.
- No `${{ }}` expression inside a `run:` block. PR-controlled text and
  ids reach shell steps through `env:` only, and ids are checked to be
  decimal before they enter a URL.
- Every action is pinned by commit SHA; `ocr` by exact version with
  `OCR_NO_UPDATE=1`.
- Credential values are masked the moment they are resolved.
- The cause set is closed. Every run that is not skipped ends with a
  record and a stated cause.
- Reactions are best effort: they never fail a run, and only the
  workflow's own reactions are ever removed.
- The PR's code is read, never executed.

## Making a change

- Defect: cut the Issue first (evidence, mechanism), then a RED test that
  fails for the reported reason, then the fix. Feature: the authority is
  an owner ruling or an issue; record it.
- Work in a worktree off `origin/master`; one PR per task.
- Keep logic out of the YAML. A new step is a `bin/ocr-review` subcommand
  plus a pure helper in `lib/ocr-review/`, tested with fakes (the io tests
  inject `fetch`, `git`, `op`, `readFile`, a clock and a step recorder).
  Real-process behavior (pipes, PATH lookups) gets a real-process test,
  as `test/ocr_review_git.test.mjs` does with a fake `git` on PATH.
- A new failure cause touches every enumeration: `CAUSES` (and
  `STEP_FAILURE_CAUSES` when a step declares it) and the cause text in
  `lib/ocr-review/record.mjs`, the step's entry in `REVIEW_STEPS` or
  `AUTHORIZE_STEPS` in `bin/ocr-review`, and the cause list in
  `docs/ocr-review.md`. Stats count causes by name and need no edit.
- A new job output must be declared on the job and read by the report
  through `needs:`; the workflow test asserts the wiring.
- A design-level change appends one Key Decisions row to the design
  record, citing its issue or ruling. Never edit the body.
- Run, all green, before committing:
  - `bash test/smoketest_ocr_review.sh`
  - `/bin/bash test/smoketest_seed_ocr_review.sh`
  - `/bin/bash test/syntax_sweep.sh`
  - `shellcheck` on any changed shell

## Proving it live

Tests cannot run the workflow; only a real `/ocr` can. The pilot is
Nine-At-A-Time-Media/Spot-the-clone (private, on the runner pool).

- After the PR merges, bump the pilot's caller: replace BOTH SHAs in
  `.github/workflows/ocr-review-caller.yml` (the `uses:` ref and
  `tools_ref`) with the merge commit, in a PR there. `uses:` pins the
  YAML; `tools_ref` pins the `bin/` and `lib/` code the YAML runs. A
  reusable workflow cannot learn which commit it was called at, so the
  caller passes it twice, and the two must match.
- Comment `/ocr` on an open PR there. Expect `eyes` within about 30 s
  (the authorize job on a fresh pool container), then the summary comment
  and a thumb. A reaction can need a page reload to show.
- Follow the run: `gh run list -R <repo> --workflow ocr-review-caller.yml`,
  then `gh run view <id> -R <repo> --log-failed`. A step crash shows as
  cause `unexpected` naming the step; its stack trace is in that log.
- `bin/seed-ocr-review -o <owner> status` lists each adopter's pin as
  current, stale, mismatch or placeholder.

## Changing a pinned dependency

- **The upstream action** (`alibaba/open-code-review`): read its
  `action.yml` at the new SHA and re-verify everything the verdict and
  report rely on, before moving the pin:
  - the outputs `comments_total`, `comments_inline`, `comments_routed`,
    `comments_skipped`, `comments_failed` and `summary_comment_url`;
  - `OCR_EXIT_CODE` written to `GITHUB_ENV` after `ocr review`, so the
    Verdict step can tell an `ocr` failure from any other;
  - `ocr`'s JSON result carries the resolved range and the reviewed files;
  - `ocr`'s agent tools are still read-only (no shell).

  Bump `ocr_version` and the `OCR_VERSION` env together with the action
  SHA.
- **The 1Password CLI** on the pool: in tds-internal, re-download the zip,
  re-hash it, re-verify its signature against the pinned key fingerprint,
  and replace `OP_VERSION` and `OP_SHA256` together; then the laptop
  deploy (`services/ci-runner-pool/scripts/deploy-laptop.zsh`). A new
  image reaches new jobs gradually after a deploy, so allow a few minutes
  before judging it.
- **The gateway's status codes:** `GATEWAY_STATUS` in
  `lib/ocr-review/gateway.mjs` (507 deadline, 503 ollama down) is mirrored
  by hand from the route in `lmde/components/ollama-gateway/route/`.
  Change both in one PR.

## Review

- Self-review every PR with a fresh-context sub-agent (the self-review
  skill) and post the epilogue on the PR.
- Codex reviews only when the owner summons it; an agent never posts
  `@codex review`. Copilot is out of quota.

## Lessons from the pilot

- The pool image lacked `gpg`, so the 1Password CLI install died
  (`spawn gpg ENOENT`). Fixed in the image and by using the image's
  baked-in `op` (Issue#446).
- ollama refuses a non-loopback `Host`, so the route rewrites it
  (Issue#444).
- A git child that exits before reading its stdin raised an unhandled
  EPIPE, which hid git's error and turned a successful review into
  `unexpected` (Issue#449).
- An unexpected red on a step after `ocr` succeeded is our code, not the
  engine: read that step's log before suspecting the gateway or model.
