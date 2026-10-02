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
reviewed something and posted what it found, or it says on the PR, loudly,
why it did not.

---

## Goals

- **G1 Dispatch.** `gh workflow run <caller workflow> -R <owner>/<repo>
  -f pr=<N>`, run by Todd or by an agent holding Todd's `gh` credentials,
  reviews PR N. Every run that is not skipped ends with a summary comment
  on PR N stating its outcome -- including a failed run, which names its
  cause. The one exception is `pr-not-open` (Outcomes).
- **G2 Comment.** A PR comment whose body starts with `/ocr`, from an author
  whose association with the repo is OWNER, MEMBER or COLLABORATOR,
  reviews that PR. A comment from anyone else, or any comment not starting
  with `/ocr`, is skipped by a job that has no access to secrets; the job
  that loads credentials never starts.
- **G3 Findings on the PR.** Each finding `ocr` reports is posted on the PR
  at the lines it is about, or in the summary comment when it cannot be
  anchored inline. A finding whose inline comment fails to post is listed
  in the summary comment and counted in `findings_failed`; the run stays a
  success, and no finding is dropped silently. The summary names the
  commit range reviewed: whatever range the upstream action resolves for
  the PR at its current head.
- **G4 No false negatives.** A PR's *reviewable files* are its changed
  files minus a declared exclusion class (deleted files, binaries,
  generated and vendored files, lockfiles), decided by this workflow, not
  by `ocr`'s own file selection. If there are reviewable files and `ocr`
  reviewed none of them, the run fails with cause `reviewed-nothing`. If
  there are none, the run succeeds with `files_reviewed: 0` and cause
  `nothing-reviewable`, and the summary says so.
- **G5 Fast, loud failure on an unreachable model.** Before reviewing, the
  run probes the gateway with the configured model. It classifies the
  answer by the gateway's response contract (OLLAMA-GATEWAY.DESIGN.md,
  API / Interface: the deadline proxy's retryable 5xx is distinct from the
  edge's tunnel-down 5xx), not by status code alone:
  - a refusal by Access (302 or 403) fails within 1 minute, cause
    `credential`;
  - the edge's tunnel-down 5xx, or the proxy's "ollama down" 5xx, fails
    within 1 minute, cause `gateway-down`;
  - a non-Access 4xx for the model (e.g. an unknown model from a dispatch
    override) fails within 1 minute, cause `model-not-found`;
  - the proxy's retryable "no first byte before the deadline" 5xx is
    retried until the model answers, for at most 6 minutes, then fails,
    cause `cold-model`.
- **G6 Adoption is a copy and a seed.** A repo of either owner adopts the
  review by copying one caller workflow file and having its secret and
  variables seeded by `bin/seed-ocr-review`; no other change to the repo.
- **G7 Every run that is not skipped leaves a record.** It writes one
  machine-readable record (Data Model) to its job summary and as a run
  artifact. A tds-utils script reads those records across repos and
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
   |  uses: 9atatimer/tds-utils/.github/workflows/ocr-review.yml@<ref>
   v
 reusable workflow (tds-utils, public -- callable from both owners)
   job: authorize    NO secret access. Skip, or fail (fork,
                     pr-not-open), or approve.
          | needs: (runs only on approval)
          v
   job: review       credentials -> one GitHub secret (a 1Password
                                    service account); the item
                                    reference from a per-owner variable
                     probe        -> gateway warm-up, classified (G5)
                     review       -> upstream alibaba/open-code-review
                                     action @<sha>, ocr @<exact version>,
                                     OCR_NO_UPDATE=1, telemetry off
                     verdict      -> reviewable-files check (G4)
                     report       -> summary comment, job summary,
                                     artifacts (G1, G7, G8)
          |
          |  HTTPS + gateway credential headers
          v
 Ollama Gateway (OLLAMA-GATEWAY.DESIGN.md) -> laptop's model
```

Dependencies point from the edges inward: the reusable workflow knows the
gateway only as a URL, a model name and credential headers read from the
caller's configuration; it names no hostname, vault or item.

---

## Design

### Caller workflow (each adopting repo)

| Responsibility | Details |
|---|---|
| Triggers | `workflow_dispatch` with a `pr` input; `issue_comment` (created). Nothing else |
| Delegate | One job that `uses:` the reusable workflow at a pinned ref, passing the PR number and `secrets: inherit` |
| Permissions | `contents: read`, `pull-requests: write`, `issues: write` (summary comment). Nothing else |
| Shipped as | `docs/ocr-review-caller.yml` in tds-utils, copied verbatim |

### Reusable workflow (tds-utils `.github/workflows/ocr-review.yml`)

Hosted in tds-utils because a reusable workflow in a public repo can be
called from both owners (the `review-settled.yml` precedent).

#### Authorize job (no secrets)

A separate job that cannot read secrets. The review job `needs:` it and
runs only when it approves, which is what makes G2's "the job that loads
credentials never starts" true by construction.

| Check | Applies to | On failure |
|---|---|---|
| Comment body starts with `/ocr` | comment trigger | skipped |
| Author association is OWNER, MEMBER or COLLABORATOR | comment trigger | skipped |
| The PR exists and is open | both triggers | failed, `pr-not-open` |
| The PR's head repo equals its base repo | both triggers | failed, `fork` |

#### Review job (credentials)

| Step | Guarantee |
|---|---|
| Credentials | Exactly one GitHub secret, `OLLAMA_GATEWAY_OP_SA_TOKEN`: a 1Password service-account token. The gateway credential is resolved from 1Password at run time, from the item reference in the owner-scoped variable `OLLAMA_GATEWAY_OP_ITEM`. The item is the gateway's existing caller credential (gateway Credential contract), not a second one minted for this workflow. A missing secret or variable fails the run, cause `configuration`, naming what is missing. The public workflow names no vault or item |
| Endpoint | The gateway base URL from the owner-scoped variable `OLLAMA_GATEWAY_URL`; the model from `OLLAMA_GATEWAY_MODEL`, overridable per dispatch. Header names and values come from the item |
| Probe | A minimal chat completion for the model, classified per G5 |
| Review | The upstream `alibaba/open-code-review` composite action, pinned by commit SHA, with `ocr_version` exact, `OCR_NO_UPDATE=1`, telemetry unset, the endpoint and headers above, and `pr_number` from the authorize job. `ocr` exiting with an error fails the run, cause `engine-error` |
| Verdict | Computes the PR's reviewable files (G4) and compares them with the files `ocr`'s JSON result says it reviewed |
| Report | Posts the summary comment (G1, G3), writes the run record (G7) to the job summary, and uploads the record and `ocr`'s JSON result (G8) as artifacts. Runs whatever the earlier steps' outcome, so a failure is reported too |

#### API / Interface

```
Caller -> reusable workflow (workflow_call)
  inputs:   pr (number, required), model (string, optional)
  secrets:  OLLAMA_GATEWAY_OP_SA_TOKEN (inherited)
  vars:     OLLAMA_GATEWAY_OP_ITEM, OLLAMA_GATEWAY_URL, OLLAMA_GATEWAY_MODEL
            (owner scope: org variables on Nine-At-A-Time-Media,
             per-repo variables on 9atatimer, which has no org tier)
```

The run's outcomes are the State Machine's table.

### Seeder (tds-utils `bin/seed-ocr-review`)

The `bin/seed-ci-magic` shape: `status` reports, per repo, whether the
caller file is present, the secret and variables set, and the last run;
`seed` sets the secret (piped from `op read`, never an argument) and the
variables, at org scope for Nine-At-A-Time-Media and per repo for
9atatimer. Seeding is a human act per tds-internal policy; the script is
what the human runs.

### Stats (tds-utils `bin/ocr-review-stats`)

Reads the run records (G7) from the adopting repos' workflow runs through
`gh` and reports, per period, runs by outcome and failures by cause. It is
read-only.

---

## State Machine

One run's lifecycle. The table below is the single source of truth for
outcomes; the diagram draws it.

```
 TRIGGERED --(not /ocr, or not authorized)--> SKIPPED
     |
     +--(PR missing/closed: pr-not-open; fork head: fork)--> FAILED
     v
 AUTHORIZED --(secret/variable missing: configuration)-----> FAILED
     v
 PROBING ----(credential | gateway-down | model-not-found
              | cold-model after 6 min)--------------------> FAILED
     v
 REVIEWING --(engine-error)--------------------------------> FAILED
     v
 JUDGED -----(reviewable files, none reviewed:
              reviewed-nothing)----------------------------> FAILED
     |
     +--(files reviewed)-------------------> SUCCEEDED (cause null)
     +--(no reviewable files)--------------> SUCCEEDED (nothing-reviewable)
```

| Terminal state | Reached from | `outcome` | `cause` | Record written | Summary comment on the PR |
|---|---|---|---|---|---|
| SKIPPED | TRIGGERED | -- | -- | no | no |
| FAILED | TRIGGERED | `failure` | `pr-not-open` | yes | no (there may be no open PR to comment on) |
| FAILED | TRIGGERED | `failure` | `fork` | yes | yes |
| FAILED | AUTHORIZED | `failure` | `configuration` | yes | yes |
| FAILED | PROBING | `failure` | `credential`, `gateway-down`, `model-not-found` or `cold-model` | yes | yes |
| FAILED | REVIEWING | `failure` | `engine-error` | yes | yes |
| FAILED | JUDGED | `failure` | `reviewed-nothing` | yes | yes |
| SUCCEEDED | JUDGED | `success` | null | yes | yes, with findings |
| SUCCEEDED | JUDGED | `success` | `nothing-reviewable` | yes | yes |

---

## Data Model

```
run record (JSON, one per run that is not skipped; job summary + artifact)
+-- repo, pr, head_sha, range       what was reviewed
+-- trigger                         dispatch | comment
+-- model, ocr_version              what reviewed it
+-- outcome                         success | failure
+-- cause                           null | a cause from the State Machine
+-- files_reviewable, files_reviewed
+-- findings_posted, findings_failed
+-- started_at, finished_at
```

---

## Data Warehouse

Nothing is ledgered in a store of our own. The run records live as GitHub
job summaries and run artifacts, which GitHub retains for 90 days by
default; `bin/ocr-review-stats` reads them from there. Whether 90 days is
long enough to judge the Trial is Open Question Q2.

---

## Security Considerations

- **Who can start a review.** Dispatch needs write access to the repo
  (GitHub's rule for `workflow_dispatch`). A comment starts one only from
  OWNER, MEMBER or COLLABORATOR, checked in a job with no secret access.
  The gate distinguishes authenticated collaborators from everyone else,
  not humans from LLMs: an agent holding Todd's token is the same principal
  as Todd on both trigger paths, and both paths are sanctioned for it.
- **No `pull_request_target`.** The workflow never runs a PR's own
  workflow definition with this repo's secrets; fork heads fail before any
  secret is read.
- **The PR's code is read, never run.** The runner checks the PR out so
  `ocr` can read it; no step executes anything from it.
- **`ocr` holds the gateway credential.** It runs in the job that loaded
  the credential and could carry it off; a leak lets the holder get
  completions from the laptop's model and nothing more (gateway G3, G4).
  Accepted for the first cut (Todd, PR #364); issue #365. The mitigation in
  the meantime is upstream's tool surface: at the pinned SHA, `ocr`'s agent
  tools are read-only (file read, search, diff read, comment), with no
  shell. Moving the pin requires re-verifying that.
- **The service-account token's reach.** The one GitHub secret can read
  only the vault holding gateway caller credentials (the tds-internal edge
  record keeps that vault to those items). A leaked token exposes the
  gateway credential, which is the same exposure as the item itself, and no
  other secret.
- **Least privilege.** The review job's token has only `contents: read`,
  `pull-requests: write` and `issues: write`. Actions are pinned by SHA.
  `ocr` is pinned exactly and never self-updates (`OCR_NO_UPDATE=1`).
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
| Triggers | `workflow_dispatch` (PR number) and `/ocr` comments | On demand by a human or an LLM (concept); an LLM uses `gh workflow run` or `/ocr` under Todd's token |
| Who may trigger by comment | GitHub's OWNER, MEMBER or COLLABORATOR association; no seam | GitHub's own permission model; the adopting repos have one maintainer, and adding a reviewer is granting collaborator access. A configurable policy would be a seam with no second implementation |
| Authorization before credentials | A separate job with no secret access, gating the review job by `needs:` | Makes G2 true by construction rather than by step ordering |
| Engine packaging | Upstream composite action, pinned by SHA, wrapping an exact `ocr` version | Upstream already resolves PR ranges, posts inline comments and a summary, and takes a `pr_number` input |
| Shared workflow home | tds-utils (public), `workflow_call` | Callable from both owners (`review-settled.yml` precedent) |
| Credential delivery | One GitHub secret: the 1Password service-account token; the gateway credential resolved at run time | tds-internal credentials policy |
| Per-owner axis | Seam = owner-scoped variables (`OLLAMA_GATEWAY_OP_ITEM`, `_URL`, `_MODEL`) | Splitting owners or moving the gateway is a variable change; the public repo names no private identifier |
| Gateway endpoint axis | Seam = URL + credential headers from configuration | The gateway's caller contract; nothing Cloudflare-specific in the workflow |
| Model axis | Seam = a variable with a per-dispatch override | The model is a detail (concept: "whatever gets it done") |
| Cold model | Probe and retry the gateway's retryable deadline 5xx before reviewing | The gateway answers before the edge's limit (gateway Key Decisions); the caller owns retrying |
| What counts as reviewable | Decided by this workflow from the PR's changed files, independent of `ocr`'s selection | Upstream issue #1454: a release selected zero files on non-empty diffs and exited 0; judging by `ocr`'s own selection would inherit that blind spot |
| Records for skipped runs | None | Every ordinary PR comment fires the comment trigger; recording those would swamp the stats |
| Run records | Job summary + artifact per non-skipped run, aggregated by a read-only script | Concept: precision and error rates visible over time, without new infrastructure |

---

## Open Questions

- **Q1 Default model.** The best model that fits on the laptop and makes
  tool calls (concept). Proposed default `qwen3.6:latest`, confirmed to
  make tool calls on 2026-10-01; Gemma is the named alternative.
- **Q2 Record retention.** Are 90 days of run artifacts enough to judge
  the Trial, or do records need a longer home?
- **Q3 Both trigger paths for LLMs.** Security Considerations states that
  an agent holding Todd's token may use either trigger. Todd to confirm.

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
- **Hardcoding the hostname, vault or item in the reusable workflow.**
  Leaks private identifiers into a public repo and kills the per-owner
  seam.
- **Judging "reviewed nothing" by `ocr`'s own file selection.** Inherits
  upstream issue #1454.
- **Authorization as a step inside the credentialed job.** A step-order
  mistake would load secrets for an unauthorized comment.
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
