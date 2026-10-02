# OCR on Demand

> **Status:** REVIEW  
> **Date:** 2026-10-02  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md) (PR #369; the road to the model); the tds-internal edge record it names  
> **Origin:** [concept: ocr-on-demand](../concepts/ocr-on-demand/CONCEPT.md), issue #363

---

## Overview

OCR on Demand is a GitHub Actions workflow that runs Alibaba's Open Code
Review (`ocr`) over a pull request, when a human or an LLM asks for it, in
any repo of the 9atatimer or Nine-At-A-Time-Media owners. The review runs on
GitHub's runner and gets its completions from the laptop's model through the
Ollama Gateway, so it spends no hosted-model quota.

The core guarantee: a review is never a silent false negative. A run either
reviewed something and posted what it found, naming any reviewable file it
did not review, or it says on the PR, loudly, why it did not.

---

## Goals

- **G1 Dispatch.** `gh workflow run <caller workflow> -R <owner>/<repo>
  -f pr=<N>`, run by Todd or by an agent holding Todd's `gh` credentials
  (agent use: Q3), reviews PR N. Every run that is not skipped ends with a
  summary comment on PR N stating its outcome -- including a failed or
  cancelled run, which names its cause. The one exception is `pr-not-open`
  (State Machine).
- **G2 Comment.** A PR comment whose body starts with `/ocr`, from an author
  whose association with the repo is OWNER, MEMBER or COLLABORATOR,
  reviews that PR with the configured model; the comment path cannot
  override the model. A comment from anyone else, or any comment not
  starting with `/ocr`, is skipped by a job that references no secret; the
  job that loads credentials never starts. An authorized `/ocr` on an issue
  that is not a PR fails as `pr-not-open`.
- **G3 Findings on the PR.** Each finding `ocr` reports is posted on the PR
  at the lines it is about, or in the summary comment when it cannot be
  anchored inline. A finding whose inline comment fails to post is listed
  in the summary comment and counted in `findings_failed`; the run stays a
  success, and no finding is dropped silently. The PR receives exactly one
  summary comment per run: the report job's. The summary names the commit
  range reviewed: whatever range the upstream action resolves for the PR at
  its current head.
- **G4 No false negatives.** A run's *reviewable files* are the files
  changed in the same commit range `ocr` was given (G3), minus a declared
  exclusion class (deleted files, binaries as git's own binary detection
  classifies them, generated and vendored files, lockfiles), decided by
  this workflow, not by `ocr`'s own file selection. Generated and vendored
  files are those marked `linguist-generated` or `linguist-vendored` by the
  repo's attributes at the PR's head revision; lockfiles are a fixed list
  kept in code. Then:
  - reviewable files exist and `ocr` reviewed none: the run fails, cause
    `reviewed-nothing`;
  - `ocr` reviewed some but not all: the run succeeds and the summary
    lists every reviewable file it did not review;
  - there are none: the run succeeds with `files_reviewed: 0` and cause
    `nothing-reviewable`, and the summary says so.
- **G5 Fast, loud failure on an unreachable model.** Before reviewing, the
  run probes the gateway with the configured model. It classifies the
  answer by the gateway's response contract (OLLAMA-GATEWAY.DESIGN.md,
  API / Interface: the deadline proxy's retryable 5xx is distinct from the
  edge's tunnel-down 5xx), not by status code alone:
  - a refusal by Access (302 or 403) fails within 1 minute, cause
    `credential`;
  - the edge's tunnel-down 5xx, the connector's 502 (deadline proxy down),
    the proxy's "ollama down" 5xx, or no HTTP answer at all (DNS, TLS or
    connect failure) fails within 1 minute, cause `gateway-down`;
  - a non-Access 4xx for the model (e.g. an unknown model from a dispatch
    override) fails within 1 minute, cause `model-not-found`;
  - the proxy's retryable "no first byte before the deadline" 5xx is
    retried until the model answers, for at most 6 minutes, then fails,
    cause `cold-model`;
  - any other answer (an undocumented 5xx, a 200 that is not a completion)
    fails within 1 minute, cause `unexpected`.
- **G6 Adoption is a copy and a seed.** A repo of either owner adopts the
  review by copying one caller workflow file and having its secret and
  variables seeded by `bin/seed-ocr-review`; no other change to the repo.
  Taking a later reusable-workflow version is a one-line bump of the
  caller's pinned SHA.
- **G7 Every run that is not skipped leaves a record.** It writes one
  machine-readable record (Data Model) to its job summary and as a run
  artifact, including runs that fail in the authorize job and runs that are
  cancelled. A tds-utils script reads those records across repos and
  reports, per period, runs by outcome and failures by cause. Skipped runs
  write nothing: every ordinary PR comment fires the comment trigger, and
  those non-events would swamp the counts.
- **G8 Findings an LLM can act on.** The run attaches `ocr`'s JSON result
  (`--audience agent`) as an artifact, and the summary comment links the
  run.

---

## Non-Goals

- **Running `ocr` on the laptop.** It is untrusted; it runs only on
  GitHub's runner (concept, settled).
- **Reviewing automatically on every push.** On demand only (concept). No
  `pull_request` or `pull_request_target` trigger.
- **Fork PRs.** A PR whose head is in another repository fails with cause
  `fork`: reviewing it would run with this repo's secrets.
- **Isolating the gateway credential from `ocr`.** Issue #365.
- **Acting as a required gate reviewer.** The concept settled that an `ocr`
  review may count as a gate reviewer in place of Copilot; wiring it into
  `review-settled` is a separate change (Future Considerations).
- **Choosing the best model.** The model is a parameter with a default.
- **Hosting any review state.** No database; GitHub holds the comments, the
  runs and the artifacts.

---

## Architecture Overview

```
 human: gh workflow run / "/ocr" comment     LLM agent: gh workflow run
                     \                          /
                      v                        v
 caller workflow, in each adopting repo  (copied file; triggers only)
   |  uses: 9atatimer/tds-utils/.github/workflows/ocr-review.yml@<sha>
   |  secrets: OLLAMA_GATEWAY_OP_SA_TOKEN only
   v
 reusable workflow (tds-utils, public -- callable from both owners)
   job: authorize    references no secret. Skip, or fail (fork,
                     pr-not-open), or approve.
          | needs: (runs only on approval)
          v
   job: review       credentials -> one GitHub secret (a 1Password
                                    service account); the item
                                    reference from a per-owner variable;
                                    resolved values masked
                     probe        -> gateway warm-up, classified (G5)
                     review       -> upstream alibaba/open-code-review
                                     action @<sha>, ocr @<exact version>,
                                     OCR_NO_UPDATE=1, telemetry disabled
                     verdict      -> reviewable-files check (G4)
          |              |
          |  HTTPS + gateway credential headers
          |              v
          |   Ollama Gateway (OLLAMA-GATEWAY.DESIGN.md) -> laptop's model
          |
          | needs: authorize, review (runs unless the run was skipped,
          |        including on failure and cancellation)
          v
   job: report       references no secret. Record first, then the
                     summary comment, job summary, artifacts (G1, G7,
                     G8), from authorize's and review's outputs
```

Dependencies point from the edges inward: the reusable workflow knows the
gateway only as a URL, a model name and credential headers read from the
caller's configuration; it names no hostname, vault or item.

---

## Design

### Caller workflow (each adopting repo)

| Responsibility | Details |
|---|---|
| Triggers | `workflow_dispatch` with a `pr` input and an optional `model` input; `issue_comment` (created). Nothing else |
| Delegate | One job that `uses:` the reusable workflow pinned by commit SHA, passing the PR number, the dispatch model (dispatch only) and exactly one secret, `OLLAMA_GATEWAY_OP_SA_TOKEN`, by name. Never `secrets: inherit` |
| Permissions | `contents: read`, `pull-requests: write`, `issues: write` (summary comment). Nothing else |
| Shipped as | `docs/ocr-review-caller.yml` in tds-utils, copied verbatim |

The caller carries only the event types. What a valid `/ocr` command is,
and who may issue it, is decided in the reusable workflow, so changing the
command form is authored in one file; it reaches an adopting repo when that
repo bumps its caller's pinned SHA (`bin/seed-ocr-review status` reports
stale pins).

### Reusable workflow (tds-utils `.github/workflows/ocr-review.yml`)

Hosted in tds-utils because a reusable workflow in a public repo can be
called from both owners (the `review-settled.yml` precedent).

#### Authorize job (no secrets referenced)

A separate job that references no secret and runs nothing from the PR.
The one secret the caller passes is reachable by any job of the reusable
workflow, so this job's isolation is that it never references it; the
guarantee G2 rests on is structural: the review job `needs:` it and runs
only when it approves, so the job that loads credentials never starts for
an unauthorized trigger.

| Check | Applies to | On failure |
|---|---|---|
| Comment body starts with `/ocr` | comment trigger | skipped |
| Author association is OWNER, MEMBER or COLLABORATOR | comment trigger | skipped |
| The PR exists and is open (an issue that is not a PR fails here) | both triggers | failed, `pr-not-open` |
| The PR's head repo equals its base repo | both triggers | failed, `fork` |

The checks are point-in-time, at this job. A PR closed, or a collaborator
removed, after approval does not stop the run; a closed PR still receives
its summary comment.

#### Review job (credentials)

| Step | Guarantee |
|---|---|
| Credentials | Exactly one GitHub secret, `OLLAMA_GATEWAY_OP_SA_TOKEN`: a 1Password service-account token. The gateway credential is resolved from 1Password at run time, from the item reference in the owner-scoped variable `OLLAMA_GATEWAY_OP_ITEM`. The item is the gateway's existing caller credential (gateway Credential contract), not a second one minted for this workflow. Every resolved header value is registered for log masking before any later step runs. A missing secret or variable, an invalid token, or an item the token cannot read fails the run, cause `configuration`, naming what is missing or unreadable. The public workflow names no vault or item |
| Endpoint | The gateway base URL from the owner-scoped variable `OLLAMA_GATEWAY_URL`; the model from `OLLAMA_GATEWAY_MODEL`, overridable per dispatch only. Header names and values come from the item |
| Probe | A minimal chat completion for the model, classified per G5. Request and response headers are never logged |
| Review | The upstream `alibaba/open-code-review` composite action, pinned by commit SHA, with `ocr_version` exact, `OCR_NO_UPDATE=1`, telemetry explicitly disabled, debug/verbose output off, its own summary comment disabled, the endpoint and headers above, and `pr_number` from the authorize job. `ocr` exiting with an error fails the run, cause `engine-error` |
| Verdict | Computes the reviewable files (G4) over the range the action resolved and compares them with the files `ocr`'s JSON result says it reviewed. Required outputs of the pinned action/`ocr` version: the resolved range, the per-file reviewed list, and per-finding post status (posted inline, unanchorable, or failed). If any is missing or unparseable, the run fails, cause `engine-error`, never "nothing to compare" or "nothing failed". Moving the pin requires re-verifying that all three are exposed and that the upstream summary can still be disabled |

#### Report job (no secrets referenced)

Runs after authorize and review whatever their outcome, including
cancellation, unless the run was skipped. It is a job, not a step, because
a run that fails in authorize has no review job to host a step; it
references no secret, so G2 holds for it too.

| Responsibility | Guarantee |
|---|---|
| Run record | Written first, to the job summary and as an artifact (G7), so a later failure in this job cannot lose it |
| Summary comment | Posted per the State Machine table (G1, G3, G4). If posting fails, the job fails, so the run concludes red in the Actions UI; the record is already written |
| `ocr` result | Uploaded as an artifact when the review job produced one (G8) |
| Cause of last resort | A run that ended in a state no other cause covers (a step outside `ocr` failing, a job timeout) gets cause `unexpected` with the failing job and step named |

Comment bodies carry PR-controlled text (file paths, diff excerpts,
findings). That text reaches any shell step only through environment
variables or files, never through `${{ }}` interpolation in a `run:` block;
this holds for every job, since each holds a `GITHUB_TOKEN` with write
scopes.

#### API / Interface

```
Caller -> reusable workflow (workflow_call)
  inputs:   pr (number, required), model (string, optional; dispatch only)
  secrets:  OLLAMA_GATEWAY_OP_SA_TOKEN (passed by name; never inherit)
  vars:     OLLAMA_GATEWAY_OP_ITEM, OLLAMA_GATEWAY_URL, OLLAMA_GATEWAY_MODEL
            (owner scope: org variables on Nine-At-A-Time-Media,
             per-repo variables on 9atatimer, which has no org tier)
```

The run's outcomes are the State Machine's table.

### Seeder (tds-utils `bin/seed-ocr-review`)

The `bin/seed-ci-magic` shape: `status` reports, per repo, whether the
caller file is present and which reusable-workflow SHA it pins, the secret
and variables set, and the last run; `seed` sets the secret (piped from
`op read`, never an argument) and the variables, at org scope for
Nine-At-A-Time-Media and per repo for 9atatimer. Seeding is a human act per
tds-internal policy; the script is what the human runs.

### Stats (tds-utils `bin/ocr-review-stats`)

Reads the run records (G7) from the adopting repos' workflow runs through
`gh` and reports, per period, runs by outcome and failures by cause. It is
read-only, and handles every `record_version` still within retention.

---

## State Machine

One run's lifecycle. The table below is the single source of truth for
outcomes; the diagram draws it. Every terminal state except SKIPPED is
reported by the report job.

```
 TRIGGERED --(not /ocr, or not authorized)--> SKIPPED
     |
     +--(PR missing/closed/not a PR: pr-not-open; fork head: fork)--> FAILED
     v
 AUTHORIZED --(secret/variable missing or unreadable: configuration)-> FAILED
     v
 PROBING ----(credential | gateway-down | model-not-found
              | cold-model after 6 min | unexpected)---------> FAILED
     v
 REVIEWING --(engine-error: ocr error, or result missing
              range / reviewed files / post status)----------> FAILED
     v
 JUDGED -----(reviewable files, none reviewed:
              reviewed-nothing)------------------------------> FAILED
     |
     +--(files reviewed)-------------------> SUCCEEDED (cause null)
     +--(no reviewable files)--------------> SUCCEEDED (nothing-reviewable)

 any non-terminal state --(other step failure or timeout: unexpected)--> FAILED
 any non-terminal state --(run cancelled)-----------------------------> CANCELLED
```

| Terminal state | Reached from | `outcome` | `cause` | Record written | Summary comment on the PR |
|---|---|---|---|---|---|
| SKIPPED | TRIGGERED | -- | -- | no | no |
| FAILED | TRIGGERED | `failure` | `pr-not-open` | yes | no (there may be no open PR to comment on) |
| FAILED | TRIGGERED | `failure` | `fork` | yes | yes |
| FAILED | AUTHORIZED | `failure` | `configuration` | yes | yes |
| FAILED | PROBING | `failure` | `credential`, `gateway-down`, `model-not-found`, `cold-model` or `unexpected` | yes | yes |
| FAILED | REVIEWING | `failure` | `engine-error` | yes | yes |
| FAILED | JUDGED | `failure` | `reviewed-nothing` | yes | yes |
| FAILED | any non-terminal | `failure` | `unexpected` (names the failing job and step) | yes | yes |
| CANCELLED | any non-terminal | `cancelled` | `cancelled` | yes | yes |
| SUCCEEDED | JUDGED | `success` | null | yes | yes, with findings, failed-to-post findings and any unreviewed reviewable files |
| SUCCEEDED | JUDGED | `success` | `nothing-reviewable` | yes | yes |

A run whose summary comment fails to post keeps its record's `outcome`
and `cause`, and concludes as a failed workflow run (Report job).

---

## Data Model

```
run record (JSON, one per run that is not skipped; job summary + artifact)
+-- record_version                  schema version of this record
+-- repo, pr, trigger               always present; trigger: dispatch | comment
+-- head_sha, range                 null if the run ended before REVIEWING resolved them
+-- model                           null until resolved: null if the run ended
                                    before AUTHORIZED, or on a `configuration`
                                    failure that left it unresolved
+-- ocr_version                     null if the run ended before AUTHORIZED
+-- outcome                         success | failure | cancelled
+-- cause                           null | a cause from the State Machine
+-- failing_step                    set only when cause is unexpected
+-- files_reviewable, files_reviewed  counts; null before JUDGED
+-- findings_posted, findings_failed  counts; null before JUDGED
+-- started_at, finished_at         always present
```

`record_version` is the seam for the record's own evolution: callers pin
different reusable-workflow SHAs, so records of several versions coexist
within retention.

---

## Data Warehouse

Nothing is ledgered in a store of our own. The run records live as GitHub
job summaries and run artifacts, which GitHub retains for 90 days by
default; `bin/ocr-review-stats` reads them from there. Whether 90 days is
long enough to judge the concept's Trial (its evaluation of `ocr` as a
reviewer; see [concept](../concepts/ocr-on-demand/CONCEPT.md)) is Open
Question Q2.

---

## Security Considerations

- **Who can start a review.** Dispatch needs write access to the repo
  (GitHub's rule for `workflow_dispatch`). A comment starts one only from
  OWNER, MEMBER or COLLABORATOR, checked in a job that references no
  secret. The gate distinguishes authenticated collaborators from everyone
  else, not humans from LLMs: an agent holding Todd's token is the same
  principal as Todd on both trigger paths. Whether both paths are
  sanctioned for an agent is pending Q3; this design asserts only that the
  gate cannot tell them apart.
- **Collaborators are trusted.** A collaborator can push adversarial
  content to a same-repo branch and trigger a review of it. That steers at
  most what `ocr` reads and writes in its comments, within `ocr`'s
  read-only tool surface and the gateway credential's reach (completions
  only). Accepted: collaborator access already grants more than this.
- **The model override is dispatch-only.** Only `workflow_dispatch`
  (write access) can choose a model; a comment uses the configured one.
- **No `pull_request_target`.** The workflow never runs a PR's own
  workflow definition with this repo's secrets; fork heads fail before any
  secret is read.
- **The PR's code is read, never run.** The runner checks the PR out so
  `ocr` can read it; no step executes anything from it.
- **Only one caller secret crosses into the reusable workflow.** The caller
  passes `OLLAMA_GATEWAY_OP_SA_TOKEN` by name, never `secrets: inherit`, so
  no other secret of an adopting repo reaches public workflow code. The
  caller pins the reusable workflow by SHA, so a push to tds-utils does not
  change code that runs with adopting repos' secrets until each repo bumps
  its pin.
- **`ocr` holds the gateway credential.** It runs in the job that loaded
  the credential and could carry it off; a leak lets the holder get
  completions from the laptop's model and nothing more (gateway G3, G4).
  Accepted for the first cut (Todd, PR #364); issue #365. The mitigation in
  the meantime is upstream's tool surface: at the pinned SHA, `ocr`'s agent
  tools are read-only (file read, search, diff read, comment), with no
  shell. Moving the pin requires re-verifying that.
- **The resolved credential stays out of logs.** GitHub masks only values
  it received as secrets; header values fetched from 1Password at run time
  are registered for masking before use, the probe never logs headers, and
  debug/verbose output is off on the probe and review steps. Logs and job
  summaries of public repos are world-readable, so this is load-bearing.
- **The service-account token's reach.** The one GitHub secret can read
  only the vault holding gateway caller credentials (the tds-internal edge
  record keeps that vault to those items). A leaked token exposes the
  gateway credential, which is the same exposure as the item itself, and no
  other secret.
- **Least privilege.** The workflow token has only `contents: read`,
  `pull-requests: write` and `issues: write`. Only the review job
  references the gateway secret. Actions and the reusable workflow are
  pinned by SHA. `ocr` is pinned exactly and never self-updates
  (`OCR_NO_UPDATE=1`).
- **"No secret" is not "no token."** The authorize and report jobs hold the
  ambient `GITHUB_TOKEN` with write scopes. PR-controlled text (findings,
  paths, branch names, comment bodies) never reaches a shell by `${{ }}`
  interpolation in a `run:` block; it passes through environment variables
  or files. This closes Actions script injection in every job.
- **Prompt injection from the PR.** A PR's content can steer what `ocr`
  writes in its comments. Findings are data for a human or an LLM to
  triage, never instructions; the self-review and gates skills already
  treat review output that way.
- **Public repo hygiene.** The reusable workflow and the caller name no
  hostname, vault or item; those are owner-scoped variables, recorded in
  the tds-internal registry.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the review runs | GitHub-hosted runner | `ocr` is untrusted; never on the laptop (concept) |
| Triggers | `workflow_dispatch` (PR number) and `/ocr` comments | On demand by a human or an LLM (concept); agent use of each path is Q3 |
| Trigger shape | Fixed: the two event types in the caller, the `/ocr` prefix in the reusable workflow; no seam | One caller template; a new command form is authored in one file and reaches each repo with its pin bump, and a new event type (e.g. labels) is rare enough to justify re-copying the caller |
| Reusable-workflow ref | Caller pins by commit SHA; repos upgrade by bumping the pin | Code that runs with an adopting repo's secret changes only when that repo opts in; consistent with pinning every action by SHA |
| Secret passing | The one secret by name; never `secrets: inherit` | Keeps every other secret of the adopting repo out of public workflow code |
| Who may trigger by comment | GitHub's OWNER, MEMBER or COLLABORATOR association; no seam | GitHub's own permission model; the adopting repos have one maintainer, and adding a reviewer is granting collaborator access. A configurable policy would be a seam with no second implementation |
| Authorization before credentials | A separate job referencing no secret, gating the review job by `needs:` | Makes G2 true by construction rather than by step ordering |
| Reporting | A separate report job, referencing no secret, after authorize and review, writing the record before commenting | Authorize-stage failures have no review job to report them (G1, G7), reporting must not need credentials, and a comment failure must not lose the record |
| Engine packaging | Upstream composite action, pinned by SHA, wrapping an exact `ocr` version; no seam | Upstream already resolves PR ranges, posts inline comments and takes a `pr_number` input; one engine, so a port would have one implementation (Rejections) |
| Summary comment owner | The report job; upstream's own summary disabled | One summary per run, so G3's "the summary comment" is unambiguous |
| Shared workflow home | tds-utils (public), `workflow_call` | Callable from both owners (`review-settled.yml` precedent) |
| Credential delivery | One GitHub secret: the 1Password service-account token; the gateway credential resolved at run time and masked | tds-internal credentials policy |
| Per-owner axis | Seam = owner-scoped variables (`OLLAMA_GATEWAY_OP_ITEM`, `_URL`, `_MODEL`) | Splitting owners or moving the gateway is a variable change; the public repo names no private identifier |
| Per-owner seam granularity | One write on Nine-At-A-Time-Media (org variables); one write per adopting repo on 9atatimer, done by the seeder | 9atatimer is a user account with no org tier. Accepted: the seeder amortizes the N writes and `status` reports drift |
| Gateway endpoint axis | Seam = URL + credential headers from configuration | The gateway's caller contract; nothing Cloudflare-specific in the workflow |
| Model axis | Seam = a variable with a per-dispatch override | The model is a detail (concept: "whatever gets it done") |
| Cold model | Probe and retry the gateway's retryable deadline 5xx before reviewing | The gateway answers before the edge's limit (gateway Key Decisions); the caller owns retrying |
| What counts as reviewable | Decided by this workflow from the files changed in the range `ocr` was given, independent of `ocr`'s selection | Upstream issue #1454: a release selected zero files on non-empty diffs and exited 0; judging by `ocr`'s own selection would inherit that blind spot. Same range, so a re-review is judged against what it was asked to review |
| Missing engine output | No resolved range, reviewed-file list or per-finding post status fails as `engine-error` | An absent field must never read as "nothing to compare" or "nothing failed" |
| Closed cause set | `unexpected` (naming the failing step) and `cancelled` cover every end no other cause names | The core guarantee needs every non-skipped run to say why; an unanticipated failure must not be causeless |
| Partial coverage | Succeeds, with unreviewed reviewable files listed in the summary | Loud without failing a run that did review something |
| Records for skipped runs | None | Every ordinary PR comment fires the comment trigger; recording those would swamp the stats |
| Run records | Job summary + artifact per non-skipped run, versioned by `record_version`, aggregated by a read-only script | Concept: precision and error rates visible over time, without new infrastructure; pinned callers mean versions coexist |

---

## Open Questions

- **Q1 Default model.** The best model that fits on the laptop and makes
  tool calls (concept). Proposed default `qwen3.6:latest`, confirmed to
  make tool calls on 2026-10-01; Gemma is the named alternative.
- **Q2 Record retention.** Are 90 days of run artifacts enough to judge
  the Trial, or do records need a longer home?
- **Q3 Both trigger paths for LLMs.** May an agent holding Todd's token
  use either trigger path? Todd to confirm before APPROVED; the answer
  becomes a Key Decisions row and Security Considerations is updated to
  match. A precondition for the freeze, not deferrable.
- **Q4 Dependency file name.** The gateway doc is linked as
  `OLLAMA-GATEWAY.DESIGN.md`; the File Naming rule gives
  `DESIGN.OLLAMA-GATEWAY.md`. Whether that doc is renamed (and this link
  updated) is decided in PR #369, not here.

---

## Rejections

- **Running `ocr` on the laptop, natively or in a container.** Native was
  torn out on 2026-10-01 (issue #362); containerized is out of scope for
  the PoC and MVP.
- **`pull_request_target`.** Runs with secrets on fork code paths;
  upstream's example uses it, and it is the one trigger this design forbids.
- **Automatic review on every push.** The concept is on-demand.
- **Our own `ocr` invocation instead of the upstream action.** Re-implements
  range resolution and comment posting the action already does.
- **A review-engine port (ocr vs another engine).** One engine, one
  implementation; the self-review skill already owns engine selection.
- **A configurable trigger shape.** One caller template and one command;
  a parameter for it would be a seam with no second implementation.
- **Calling the reusable workflow at a moving ref (`@main`, `@v1`).** Every
  push to tds-utils would change code running with adopting repos' secrets.
- **`secrets: inherit`.** Hands every secret of the adopting repo to public
  workflow code that needs one.
- **Hardcoding the hostname, vault or item in the reusable workflow.**
  Leaks private identifiers into a public repo and kills the per-owner
  seam.
- **Judging "reviewed nothing" by `ocr`'s own file selection.** Inherits
  upstream issue #1454.
- **Authorization as a step inside the credentialed job.** A step-order
  mistake would load secrets for an unauthorized comment.
- **Reporting as a step in the review job.** Cannot report failures
  decided before that job starts.
- **Keeping upstream's summary alongside ours.** Two summaries per run make
  "the summary comment" ambiguous.
- **Failing on partial coverage.** A run that reviewed real files would
  discard its findings; listing the gap keeps it loud.
- **A database or bucket for run records in the first cut.** GitHub's run
  history holds them; a store is deferred until retention proves short
  (Q2).

---

## Future Considerations

- **Counting as a gate reviewer.** Add `ocr` to `review-settled`'s reviewer
  group, so an `ocr` review on the head can settle a PR in place of
  Copilot (concept, settled as allowed).
- **Precision tracking.** Join findings with how their threads were
  resolved (accepted, rebutted) to report `upheld k of n` per model.
- **Per-owner credentials** and **credential isolation** -- gateway Future
  Considerations, issue #365.
- **Request shaping** (rates, sizes) -- the gateway's deadline proxy, v2.

---

## Related Documents

- [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md) -- the road to the model
- [concept: ocr-on-demand](../concepts/ocr-on-demand/CONCEPT.md) -- origin
  (non-binding)
- `.github/workflows/review-settled.yml` -- the cross-owner reusable
  workflow precedent
- `bin/seed-ci-magic` and `docs/seed-ci-magic.md` -- the seeder precedent
