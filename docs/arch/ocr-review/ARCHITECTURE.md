# OCR on Demand -- as-built

What is deployed, not what was designed. Living; edit it when a release
moves the workflow or an adopter's pin.

- Design: [OCR-ON-DEMAND.DESIGN.md](../../design/OCR-ON-DEMAND.DESIGN.md)
  (APPROVED; the authority for intent). Open drift: Issue#453, Issue#454.
- Runbook: [docs/ops/ocr-review.md](../../ops/ocr-review.md) (adopt, seed,
  trigger, read results, change it).
- Diagram: [ocr-review.html](./ocr-review.html).
- The road to the model: the [Ollama Gateway](../ollama-gateway/ARCHITECTURE.md).

## Deployment

- Published as the reusable workflow `.github/workflows/ocr-review.yml` on
  tds-utils `master` (public, so both owners can call it). It ships when
  an adopter's caller pins a commit; merging to `master` changes nothing
  that runs until a caller bumps its pin.
- Adopters (`bin/seed-ocr-review status`, 2026-10-13): one,
  Nine-At-A-Time-Media/Spot-the-clone (private, the pilot), on its
  `CI_RUNS_ON` runner pool, pinned at `11fdd05`, with the secret and the
  three variables at org scope, visibility `selected`. `status` calls the
  pin stale: PR#451 later changed comment lines in the workflow. No
  9atatimer repo has adopted it (task-053).
- First green run 2026-10-13, `/ocr` on Nine-At-A-Time-Media/Spot-the-clone
  PR#28, caller pinned at `11fdd05`:
  [run 38410635849](https://github.com/Nine-At-A-Time-Media/Spot-the-clone/actions/runs/38410635849).
  Authorize 24 s, review 65 s, report 18 s. 2 of 32 reviewable files
  reviewed, 0 findings. Three gateway requests, about 33 s of model time
  in all, including a cold model load (the gateway's `keep_alive` is
  2 m).
- Where jobs run: every job `runs-on` the caller's `CI_RUNS_ON` variable
  when set (the niners runner pool: Cloudflare Containers, a 10-minute
  container ceiling), else `ubuntu-latest`.
- Telemetry: the run record (job summary and artifact), the Actions logs,
  and `bin/ocr-review-stats` over the records. Nothing else.

## Components

| Component | Responsibility | Source |
|---|---|---|
| Caller template | The two triggers; one job that `uses:` the reusable workflow pinned by SHA and passes `pr`, `model` (dispatch only), `tools_ref` and the one secret by name | `docs/ocr-review-caller.yml`, copied to `.github/workflows/ocr-review-caller.yml` |
| Reusable workflow | Three jobs: authorize, review, report; thin YAML, each step a `bin/ocr-review` subcommand | `.github/workflows/ocr-review.yml` |
| Step commands | The composition root: env in; GitHub, git, `op` and `fetch` calls; step outputs out | `bin/ocr-review` |
| Decisions | Pure: authorize, gateway config and probe classification, host tools, reactions, verdict, record and summary, stats | `lib/ocr-review/*.mjs` |
| Seeder | `status` and `seed` per owner | `bin/seed-ocr-review` |
| Stats | Runs by outcome and failures by cause, per period | `bin/ocr-review-stats` |
| Tests | Node suites, the seeder smoketest | `test/ocr_review_*.test.mjs`, `test/smoketest_ocr_review.sh`, `test/smoketest_seed_ocr_review.sh` |

## Interface as built

```
Caller -> reusable workflow (workflow_call)
  inputs:   pr (number, required)
            model (string, default ''; the caller passes it on dispatch only)
            backend (string, default ''; dispatch only: ollama-gateway,
              cf-ai-gateway or anthropic)
            tools_ref (string, required): the tds-utils commit bin/ocr-review
              and lib/ocr-review are checked out at; the caller sets it to
              the SHA it pins uses: at                       (Issue#453)
  secrets:  OLLAMA_GATEWAY_OP_SA_TOKEN (required: false, so a missing one
              fails as `configuration` with a record, not at call time)
  vars:     OCR_BACKEND (unset is ollama-gateway), and the chosen backend's
            three: OLLAMA_GATEWAY_OP_ITEM/_URL/_MODEL,
            CF_AI_GATEWAY_OP_ITEM/_URL/_MODEL (+ _REASONING), or
            ANTHROPIC_OP_ITEM/_URL/_MODEL (Issue#559);
            CI_RUNS_ON (the caller's)
  permissions: contents read, pull-requests write, issues write
```

## Jobs, steps and tuned values

| Job | Timeout | Steps |
|---|---|---|
| `authorize` | 3 min | job `if:` prefilter (not an `issue_comment`, or the body starts with `/ocr`, case-insensitively); Fetch the tools; Set up Node; Authorize (exact `/ocr` prefix, OWNER/MEMBER/COLLABORATOR, PR open, head repo = base repo); Acknowledge the comment (`eyes`, comment trigger only, `continue-on-error`) |
| `review` | 9 min | needs `authorize` approve. Fetch the tools; Set up Node; Stage the tools (to `$RUNNER_TEMP`, since the upstream action clears the workspace); Check the host tools; Install the 1Password CLI (only when no `op` on PATH); Credentials (the one step with the secret; each value masked as read); Probe; Review (upstream action); Verdict; Upload the ocr result; Upload the review state |
| `report` | 5 min | `if: always()` unless authorize was skipped or decided skip. Note a cancelled run; Fetch the tools; Set up Node; Fetch the review state; Build the run record; Upload the run record; Post the summary comment; React with the outcome (`+1` / `-1`, removes its own `eyes`, `continue-on-error`) |

| Value | Setting | Where |
|---|---|---|
| Upstream action | `alibaba/open-code-review@fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4` (v1.12.13) | `ocr-review.yml` Review step |
| `ocr` | `ocr_version: '1.12.13'`; job env `OCR_NO_UPDATE=1`, `OCR_ENABLE_TELEMETRY=0`, `OCR_RAW_LOGGING=0`, `OCR_CONTENT_LOGGING=0` | review job |
| Action inputs | From the chosen backend's profile (`BACKEND_PROFILES`): `llm_url`, `llm_auth_token`, `llm_protocol`, `llm_use_anthropic`, `llm_auth_header`, `llm_extra_headers` from the item, `llm_extra_body`. Ollama Gateway: `<url>/v1`, placeholder `ollama` (Access headers authenticate), `openai`, body `{"thinking": {"type": "disabled"}, "reasoning_effort": "none", "stream": true}`. Cloudflare AI Gateway: `<url>/compat`, the run token (Issue#489), `openai`, body `{"stream": true}` plus `reasoning_effort` when set. Anthropic: the bare origin (ocr appends `/v1/messages`), the key, `anthropic`, `llm_auth_header: x-api-key`, body `{}` (Issue#559). Then `pr_number`, `head_sha`, `base_ref` from authorize, `stream_progress: false`, `upload_artifacts: false`, `sticky_summary: true`, `checkpoint_range`, `incremental`, `resolve_outdated` all `false` | Review step |
| Other pinned actions | `actions/checkout@3d3c42e5` (v7.0.1), `actions/setup-node@949feb24` (v7.1.0, Node 22), `1password/install-cli-action@1a3160d5` (v4.1.0, CLI 2.40.0), `actions/upload-artifact@cf430e03` (v7.0.2), `actions/download-artifact@9000827c` (v8.0.2) | `ocr-review.yml` |
| Probe request | `POST <api base><probe path>`, `{"model": ..., "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 1, "stream": false}`; the path is `/chat/completions` on the Ollama and Cloudflare backends, `/v1/messages` on Anthropic. Only the Ollama Gateway retries (the 507) | `lib/ocr-review/gateway.mjs` |
| Probe attempt timeout | 110 s (past the gateway's 90 s deadline) | `bin/ocr-review` |
| Cold-model retry | the 507 only; 10 s between attempts; no attempt starts after 6 min, so the worst case is about 7.5 min, inside the job's 9 | `lib/ocr-review/gateway.mjs` |
| Gateway status contract | `GATEWAY_STATUS`: 530 tunnel down, 502 proxy down, 503 ollama down, 507 deadline (retryable); 302/403 Access | `lib/ocr-review/gateway.mjs`, mirrored by hand from the route |
| Item fields | Ollama Gateway: `access/client id header`, `access/client id`, `access/client secret header`, `password`. Cloudflare AI Gateway: `password` (the run token). Anthropic: `credential` (an API Credential item's key) | `lib/ocr-review/gateway.mjs` |
| Artifacts | `ocr-result-<attempt>` (90 days; review job; Issue#454), `ocr-review-state-<attempt>` (1 day; review -> report hand-off; Issue#454), `ocr-review-record-<attempt>` (90 days; report job) | `ocr-review.yml` |
| Run record | `record_version` 2: the design's Data Model fields plus `backend` (Issue#481) | `lib/ocr-review/record.mjs` |
| Lockfile exclusion list | fixed in code (`LOCKFILES`) | `lib/ocr-review/verdict.mjs` |

The closed cause set (`CAUSES`): `pr-not-open`, `fork`, `configuration`,
`credential`, `gateway-down`, `model-not-found`, `cold-model`, `budget`,
`limited`, `runner-tool-missing`, `unexpected`, `engine-error`, `reviewed-nothing`,
`nothing-reviewable`, `cancelled`.

## Seams in the code

- **Per-owner configuration**: `OLLAMA_GATEWAY_OP_ITEM` (an
  `op://<vault>/<item>` reference), `OLLAMA_GATEWAY_URL`,
  `OLLAMA_GATEWAY_MODEL`: org variables on Nine-At-A-Time-Media, per-repo
  on 9atatimer. The public workflow names no hostname, vault or item.
- **Gateway contract**: URL plus header names and values read from the
  item; the probe classifies by `GATEWAY_STATUS`.
- **Runner**: the caller's `CI_RUNS_ON`; the host-tools step adapts to it
  (use the runner's `op`, else install it, which needs `gpg` and `unzip`;
  `git` always).
- **Model**: the variable, overridable by dispatch only.
- **Backend**: `OCR_BACKEND`, overridable by dispatch only; each backend is
  a profile (API suffix, probe path, protocol, auth header, body), a
  variable set, a credential reader and a probe reading in
  `lib/ocr-review/gateway.mjs`. One secret and one service account serve
  all three. The Anthropic backend's spend cap is the key's Claude Console
  workspace limit, outside this repo.
- **Record schema**: `record_version`; stats reads every version it has a
  reader for.
- **Step I/O**: every `run*` flow in `bin/ocr-review` takes its effects
  (`fetch`, `git`, `op`, `readFile`, a clock, a step recorder) as
  arguments, so the io tests inject fakes.

## Entry points (the use-case surface)

| `bin/ocr-review` subcommand | Flow | Decides with |
|---|---|---|
| `authorize` | `runAuthorize` | `authorize.mjs` `authorizeRun` |
| `ack` | `runAck` | `reaction.mjs` `ackReaction` |
| `host-tools` | `runHostTools` | `host-tools.mjs` `checkHostTools` |
| `credentials` | `runCredentials` | `gateway.mjs` `resolveGatewayConfig`, `resolveCredentials` |
| `probe` | `runProbe` | `gateway.mjs` `probeGateway` |
| `verdict` | `runVerdict` | `verdict.mjs` `reviewableFiles`, `readEngineResult`, `readPostCounts`, `judgeReview` |
| `report` | `runReport` | `record.mjs` `endOfRun`, `buildRecord`, `renderSummary` |
| `comment` | `runComment` | `record.mjs` `shouldComment` |
| `react` | `runReact` | `reaction.mjs` `outcomeReaction`, `staleOutcomeIds` |

## Flow of one run

```
/ocr comment or workflow_dispatch in the adopting repo
  -> caller job uses: tds-utils ocr-review.yml@<sha>, tools_ref=<sha>
  -> authorize: skip | fail (pr-not-open, fork) | approve (+ eyes)
  -> review: host tools -> [op install] -> credentials (masked)
       -> probe (retry 507 up to 6 min) -> upstream action (ocr 1.12.13,
          streaming, through the gateway) -> verdict (G4 over the range
          ocr resolved) -> upload ocr result, review state
  -> report: record (job summary + artifact) -> summary comment
       -> +1 / -1 reaction, eyes removed
upstream action, meanwhile: inline comments and its own sticky summary
```

## Built but not designed

Recorded here as fact; recording is not approval.

- The `tools_ref` input and the two-SHA pin: drift, Issue#453.
- The review job uploads the `ocr` result, and the verdict reaches the
  report job through the `ocr-review-state` artifact: drift, Issue#454.
- Two summary comments per PR, the `runner-tool-missing` cause, and the
  reactions: authorized by Key Decisions rows (option A; runner host
  tools; comment reactions).
- The `anthropic` backend (the Anthropic API direct, a second LLM protocol
  in the workflow; tds-utils PR#557): authorized by the Key Decisions
  row ruling Issue#559 (kept, 2026-10-18).
- The authorize job's `if:` prefilter, so an ordinary comment costs no
  runner; the exact prefix is still judged by the Authorize step.

## Radar reality

- Open Code Review (`ocr`): on the fleet radar (the tech-radar skill) at
  Trial, but that row scopes it to the self-review skill's adapter,
  "never called from anywhere else". OCR on Demand calls it through the
  upstream action. A finding for the radar's owner; the
  `alibaba/open-code-review` action itself has no row.
- 1Password CLI: Adopt (`lmde/TECH_RADAR.md`); on the pool it is the
  image's pinned, verified copy, else `1password/install-cli-action`.
- Node.js: Adopt (`lmde/TECH_RADAR.md`), Node 22 via `setup-node`.

## Lessons the shape taught

- **A reusable workflow cannot learn the commit it was called at.** The
  step code is fetched separately, so the caller names its pin twice and
  the two can disagree (Issue#453).
- **ocr skips Markdown by its own selection; the G4 verdict does not.** On
  the pilot all 30 unreviewed reviewable files were `.md` (ocr selected
  `apps/web/app/game/board.ts` and `tasks/done/.gitkeep`). The summary
  lists each one, and a PR that changes only Markdown would fail
  `reviewed-nothing` (`lib/ocr-review/verdict.mjs`, `judgeReview`). This
  is the design working as written; whether Markdown joins the exclusion
  class is an owner decision (TODO_PLAN Blockers).
- **A runner is an environment with its own host tools.** The pool image
  had no `gpg`, so the install action's signature check died and the run
  read as `unexpected` (Issue#446). Host tools are now checked before any
  credential and missing ones are named.
- **A child that exits before reading stdin turns a write into an
  unhandled EPIPE** that hides the child's own error; a clean review read
  as `unexpected` (Issue#449). `gitIn` now ignores EPIPE on the child's
  stdin and reports git's exit code and stderr.
- **The pool's 10-minute ceiling shapes the timeouts.** The review job
  gets 9 minutes; a cold model on a cold OS cache can spend most of it in
  the probe. The pilot's review took 65 s with a warm OS cache.
