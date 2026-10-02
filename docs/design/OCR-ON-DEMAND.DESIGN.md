# OCR on Demand

> **Status:** DRAFT  
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
Ollama Gateway, so it spends no hosted-model quota, and its findings land on
the PR.

---

## Goals

- **G1 Dispatch.** `gh workflow run <caller workflow> -R <owner>/<repo>
  -f pr=<N>`, run by Todd or by an agent holding Todd's `gh` credentials,
  reviews PR N: the run ends with a review summary comment on PR N.
- **G2 Comment.** A PR comment whose body starts with `/ocr`, from an author
  whose association with the repo is OWNER, MEMBER or COLLABORATOR,
  reviews that PR. A `/ocr` comment from anyone else starts no review: the
  job is skipped before any credential is loaded.
- **G3 Findings on the PR.** Each finding `ocr` reports is posted on the PR
  at the lines it is about, or in the summary comment when it cannot be
  anchored inline. The summary names the commit range reviewed.
- **G4 No false negatives.** A run that reviewed zero files on a diff that
  has reviewable files fails red, and its summary says the review reviewed
  nothing. A clean result is reported only when files were reviewed and
  produced no findings.
- **G5 Fast, loud failure on an unreachable model.** Before reviewing, the
  run probes the gateway with the configured model:
  - a refusal by Access (302 or 403) fails the run within 1 minute, naming
    the credential as the cause;
  - an unreachable laptop (the edge's tunnel-down 5xx) fails the run within
    1 minute, naming the gateway as the cause;
  - the gateway's retryable "no first byte before the deadline" 5xx (a cold
    model) is retried until the model answers, for at most 6 minutes, then
    fails naming the cold model as the cause.
- **G6 Adoption is a copy and a seed.** A repo of either owner adopts the
  review by copying one caller workflow file and having its secret and
  variables seeded by `bin/seed-ocr-review`; no other change to the repo.
- **G7 Every run leaves a record.** Each run writes one machine-readable
  record (repo, PR, range, model, outcome, cause class, files reviewed,
  findings posted) to its job summary and as a run artifact. A tds-utils
  script reads those records across repos and reports, per period, the
  failure and interruption rate by cause class.
- **G8 Findings an LLM can act on.** The run attaches `ocr`'s JSON result
  (`--audience agent`) as an artifact, and the summary comment links the
  run.

---

## Non-Goals

- **Running `ocr` on the laptop.** It is untrusted; it runs only on
  GitHub's runner (concept, settled).
- **Reviewing automatically on every push.** On demand only (concept). No
  `pull_request` or `pull_request_target` trigger.
- **Fork PRs.** A PR whose head is in another repository is refused: it
  would run with this repo's secrets.
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
   authorize   -> PR exists, same-repo head, author association (G2)
   credentials -> 1Password service account (one GitHub secret);
                  item reference from the caller's variable (per owner)
   probe       -> gateway warm-up with retries (G5)
   review      -> upstream alibaba/open-code-review action @<sha>,
                  ocr @<exact version>, OCR_NO_UPDATE=1, telemetry off
   verdict     -> zero-files check (G4)
   record      -> job summary + artifacts (G7, G8)
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
| Triggers | `workflow_dispatch` with a `pr` input; `issue_comment` (created) on PRs. Nothing else |
| Delegate | One job that `uses:` the reusable workflow at a pinned ref, passing the PR number and `secrets: inherit` |
| Permissions | `contents: read`, `pull-requests: write`, `issues: write` (summary comment). Nothing else |
| Shipped as | `docs/ocr-review-caller.yml` in tds-utils, copied verbatim |

### Reusable workflow (tds-utils `.github/workflows/ocr-review.yml`)

Hosted in tds-utils because a reusable workflow in a public repo can be
called from both owners (the `review-settled.yml` precedent).

#### Responsibilities

| Step | Guarantee |
|---|---|
| Authorize | The PR exists and is open; its head repo equals the base repo; for `issue_comment`, the body starts with `/ocr` and the author association is OWNER, MEMBER or COLLABORATOR. Otherwise the job ends here, before any secret is read (G2) |
| Credentials | Reads the gateway credential through `1password/load-secrets-action` with the service-account token from the single secret `OLLAMA_GATEWAY_OP_SA_TOKEN`. The item reference (vault and item) comes from the caller-owner variable `OLLAMA_GATEWAY_OP_ITEM`; a missing variable fails the run naming it. The public workflow names no vault or item |
| Endpoint | The gateway base URL comes from the caller-owner variable `OLLAMA_GATEWAY_URL`, the model from `OLLAMA_GATEWAY_MODEL` (overridable per dispatch). Header names and values come from the item (the gateway's credential contract) |
| Probe | Sends a minimal chat completion for the model; classifies the answer per G5; retries only the retryable deadline 5xx, within G5's bounds |
| Review | Runs the upstream `alibaba/open-code-review` composite action pinned by commit SHA, with `ocr_version` exact, `OCR_NO_UPDATE=1`, telemetry unset, the endpoint and headers above, and `pr_number` from the authorize step |
| Verdict | Reads `ocr`'s JSON result: zero files reviewed on a diff with reviewable files is a red failure (G4) |
| Record | Writes the run record (G7) to the job summary and uploads it, with `ocr`'s JSON result (G8), as artifacts |

#### API / Interface

```
Caller -> reusable workflow (workflow_call)
  inputs:   pr (number, required), model (string, optional)
  secrets:  OLLAMA_GATEWAY_OP_SA_TOKEN (inherited)
  vars:     OLLAMA_GATEWAY_OP_ITEM, OLLAMA_GATEWAY_URL, OLLAMA_GATEWAY_MODEL
            (owner scope: org variables on Nine-At-A-Time-Media,
             per-repo variables on 9atatimer, which has no org tier)

Outcome (job conclusion + record.cause):
  success      reviewed >= 1 file; findings posted (possibly zero)
  failure      cause in { unauthorized, fork, credential, gateway-down,
                          cold-model, reviewed-nothing, engine-error }
  skipped      not authorized to trigger (no secret read)
```

### Seeder (tds-utils `bin/seed-ocr-review`)

The `bin/seed-ci-magic` shape: `status` reports, per repo, whether the
caller file is present, the secret and variables set, and the last run;
`seed` sets the secret (piped from `op read`, never an argument) and the
variables, at org scope for Nine-At-A-Time-Media and per repo for
9atatimer. Seeding is a human act per tds-internal policy; the script is
what the human runs.

### Stats (tds-utils `bin/ocr-review-stats`)

Reads the run records (G7) from the adopting repos' workflow runs through
`gh` and reports, per period, runs by outcome and failure by cause class.
It is read-only.

---

## State Machine

One run's lifecycle.

```
 TRIGGERED -> AUTHORIZED -> PROBING -> REVIEWING -> JUDGED -> RECORDED
     |            |            |           |           |
     v            v            v           v           v
  SKIPPED      FAILED       FAILED      FAILED      FAILED
            (unauthorized, (credential, (engine-   (reviewed-
             fork)          gateway-     error)     nothing)
                            down, cold-
                            model)
```

| From | To | Trigger |
|---|---|---|
| TRIGGERED | SKIPPED | comment not `/ocr`, or author not authorized |
| TRIGGERED | AUTHORIZED | PR open, same-repo head, trigger authorized |
| TRIGGERED | FAILED | PR missing, closed, or a fork |
| AUTHORIZED | PROBING | credentials loaded |
| AUTHORIZED | FAILED | secret or variable missing (named in the failure) |
| PROBING | REVIEWING | model answered |
| PROBING | FAILED | Access refusal, gateway down, or still cold after 6 minutes |
| REVIEWING | JUDGED | `ocr` finished |
| REVIEWING | FAILED | `ocr` exited with an error |
| JUDGED | RECORDED | at least one file reviewed |
| JUDGED | FAILED | zero files on a reviewable diff |

Every FAILED and every RECORDED run writes its record (G7).

---

## Data Model

```
run record (JSON, one per run; job summary + artifact)
+-- repo, pr, head_sha, range       what was reviewed
+-- trigger                         dispatch | comment
+-- model, ocr_version              what reviewed it
+-- outcome                         success | failure | skipped
+-- cause                           null | one of the failure causes
+-- files_reviewed, findings_posted, findings_failed
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
  (GitHub's rule for `workflow_dispatch`); an agent dispatching uses
  Todd's credentials. A comment starts one only from OWNER, MEMBER or
  COLLABORATOR, checked before any secret is read.
- **No `pull_request_target`.** The workflow never runs a PR's own
  workflow definition with this repo's secrets; fork heads are refused.
- **The PR's code is read, never run.** The runner checks the PR out so
  `ocr` can read it; no step executes anything from it. `ocr`'s agent tools
  are read-only (file read, search, diff read, comment).
- **`ocr` holds the gateway credential.** It runs in the same job that
  loaded the credential and could carry it off; a leak lets the holder get
  completions from the laptop's model, and nothing more (gateway G3, G4).
  Accepted for the first cut (Todd, PR #364); issue #365.
- **Least privilege.** The job's token has only `contents: read`,
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
| Triggers | `workflow_dispatch` (PR number) and `/ocr` comments from collaborators | On demand by a human or an LLM (concept); an LLM uses `gh workflow run` |
| Engine packaging | Upstream composite action, pinned by SHA, wrapping an exact `ocr` version | Upstream already resolves PR ranges, posts inline comments and a summary, and takes a `pr_number` input |
| Shared workflow home | tds-utils (public), `workflow_call` | Callable from both owners (`review-settled.yml` precedent) |
| Credential delivery | One GitHub secret: the 1Password service-account token; everything else resolved at run time | tds-internal credentials policy |
| Per-owner axis | Seam = owner-scoped variables (`OLLAMA_GATEWAY_OP_ITEM`, `_URL`, `_MODEL`) | Splitting owners or moving the gateway is a variable change; the public repo names no private identifier |
| Gateway endpoint axis | Seam = URL + credential headers from configuration | The gateway's caller contract; nothing Cloudflare-specific in the workflow |
| Model axis | Seam = a variable with a per-dispatch override | The model is a detail (concept: "whatever gets it done") |
| Cold model | Probe and retry the gateway's retryable deadline 5xx before reviewing | The gateway answers before the edge's limit (gateway Key Decisions); the caller owns retrying |
| No false negatives | Zero files reviewed on a reviewable diff is a failure | Upstream issue #1454: a release selected zero files on non-empty diffs and exited 0 |
| Run records | Job summary + artifact per run, aggregated by a read-only script | Concept: precision and error rates visible over time, without new infrastructure |

---

## Open Questions

- **Q1 Default model.** The best model that fits on the laptop and makes
  tool calls (concept). Proposed default `qwen3.6:latest`, confirmed to
  make tool calls on 2026-10-01; Gemma is the named alternative.
- **Q2 Record retention.** Are 90 days of run artifacts enough to judge
  the Trial, or do records need a longer home?
- **Q3 Comment-trigger summoning by an LLM.** An LLM can also post `/ocr`
  under Todd's token. Is dispatch the only sanctioned LLM path, or are both?

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
