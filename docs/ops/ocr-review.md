# OCR on Demand -- runbook

Runs Alibaba's Open Code Review (`ocr`) over a pull request when you ask,
in any repo of 9atatimer or Nine-At-A-Time-Media, with completions from the
laptop's model through the Ollama Gateway.

- Design: `docs/design/OCR-ON-DEMAND.DESIGN.md` (APPROVED; the authority).
- As-built (what is deployed, every pin and timeout):
  `docs/arch/ocr-review/ARCHITECTURE.md`.
- Reusable workflow: `.github/workflows/ocr-review.yml`.
- Caller template: `docs/ocr-review-caller.yml`.
- Step commands: `bin/ocr-review`; decisions in `lib/ocr-review/`.
- Seeder: `bin/seed-ocr-review`. Stats: `bin/ocr-review-stats`.
- Changing the workflow or its tools: "Changing OCR on Demand", below.
- Tests: `test/smoketest_ocr_review.sh` (node suites),
  `test/smoketest_seed_ocr_review.sh` (fake `gh`/`op`). Both run in CI.

---

## Adopt a repository

- Copy `docs/ocr-review-caller.yml` verbatim to
  `.github/workflows/ocr-review-caller.yml` in the repo, on a branch, and
  land it the way that repo lands changes.
- In the copy, replace BOTH placeholder SHAs (the `uses:` pin and
  `tools_ref`) with the same tds-utils `master` commit that carries
  `.github/workflows/ocr-review.yml`. A reusable workflow cannot learn the
  commit it was called at, so the caller names it twice; `status` flags a
  mismatch.
- Seed the secret and variables (next section).
- A later version is a bump of both SHAs; `status` says when a pin is
  stale.

## Seed (a human act)

Seeding is the human's step under tds-internal credential policy. Look the
caller item's `op://<vault>/<item>` reference up in tds-internal
`ops/credentials/REGISTRY.md` -- this public repo does not name it.

```
bin/seed-ocr-review status                                   # 9atatimer
bin/seed-ocr-review -o Nine-At-A-Time-Media status
bin/seed-ocr-review -n -i '<caller item op:// reference>' -r '<SA token op:// reference>' -u '<gateway base URL>' seed   # dry run
bin/seed-ocr-review -i '<caller item op:// reference>' -r '<SA token op:// reference>' -u '<gateway base URL>' seed
bin/seed-ocr-review -o Nine-At-A-Time-Media -i '<...>' -r '<...>' -u '<...>' seed
```

- `status` is read-only: per consumer, the pin and its state, the secret,
  the three variables and the last run. Exit 0 ready, 1 not ready, 2
  could not tell. On Nine-At-A-Time-Media an org secret or variable counts
  for a repo only when its visibility reaches it: `all` reaches every repo,
  `private` only private and internal repos (never a public one), and
  `selected` the repos it lists.
- `seed` needs 1Password unlocked. It pipes the service-account token from
  `op read` into `gh secret set`, never as an argument, and sets
  `OLLAMA_GATEWAY_OP_ITEM`, `OLLAMA_GATEWAY_URL`
  (the gateway base URL from tds-internal's credential registry, passed with `-u`) and `OLLAMA_GATEWAY_MODEL`
  (`qwen3.6:latest`). On 9atatimer (no org tier) it writes each consumer
  repo. On Nine-At-A-Time-Media it writes org secrets and variables and
  never narrows or changes the visibility each already has: `all` stays
  `all`; `selected` keeps every repo it selects (every page) and adds the
  consumers; `private` stays `private`. One that does not exist yet is
  created `selected` for the consumers.
- A `private` org secret or variable never reaches a public repo, so when a
  consumer is public `seed` refuses (exit 2), naming the public repos and
  the secret or variable, before reading the token or writing anything.
  Change that one's visibility to `all`, or to `selected` repositories
  that include them, in the org's Actions settings, then re-run; or name
  only private repos on the command line.
- Re-run `seed` after a new adopter and after a rotation.

## Trigger a review

- Dispatch (write access; an agent holding Todd's token may use it, Key
  Decisions Q3):

  ```
  gh workflow run ocr-review-caller.yml -R <owner>/<repo> -f pr=<N>
  gh workflow run ocr-review-caller.yml -R <owner>/<repo> -f pr=<N> -f model=<model>
  gh workflow run ocr-review-caller.yml -R <owner>/<repo> -f pr=<N> -f backend=cf-ai-gateway
  ```

- Comment: a PR comment whose body starts with `/ocr`, from an OWNER,
  MEMBER or COLLABORATOR. The comment path always uses the configured
  model. Any other comment is skipped and leaves nothing behind.
- Fork PRs fail with cause `fork`; nothing reads the secret for them.
- On the Cloudflare backend every dispatch is billed, so check before
  spending. The PR is open and `gh pr view --json mergeable` does not say
  `CONFLICTING`: a superseded branch reviews code that is not on the
  default branch (Spot-the-clone PR#1, 2026-10-14, eight findings on a
  February branch that `main` had rebuilt). A check of the plumbing uses
  the smallest such PR. Whether a model reviews well is the bake-off's
  question (below); a dispatch on a PR with no earlier Copilot or Codex
  findings has nothing to score against and answers it with nothing.
- Reactions on the `/ocr` comment (design Key Decisions, comment
  reactions): `eyes` once the run is approved, before the review starts;
  after the summary comment, `+1` for success (including
  `nothing-reviewable`) or `-1` for a failure (including `pr-not-open` and
  `fork`) or a cancellation, and the workflow removes its own `eyes`. A
  skipped comment and a dispatch get none. A reaction that cannot be
  posted logs a warning and never fails the run; the summary comment and
  the record are the outcome of record.

## Read the result

- A PR carries two summary comments (owner ruling "option A"):
  - this workflow's, one per run: the outcome and, on failure, the cause
    (`unexpected` also names the failing job and step); on success the
    reviewed-file counts, the action's post counts and every reviewable
    file ocr did not review. `pr-not-open` posts none. ocr never selects
    Markdown, so every changed `.md` file is listed there, and a PR that
    changes only Markdown fails `reviewed-nothing`; whether Markdown joins
    the exclusion class is an open owner decision (`TODO_PLAN.md`,
    Blockers).
  - upstream's own, sticky (updated in place each run): the findings that
    could not be anchored inline and each finding that failed to post.
    Ours links it whenever the action reports its URL.
- A whole review of the head is the review mark (design Key Decisions,
  "Counting as a gate reviewer", Issue#568): when the run succeeded,
  every reviewable file was reviewed and every finding posted (or nothing
  was reviewable), this workflow's summary is posted as a COMMENT review
  on the reviewed commit, opening with `<!-- ocr-review-mark sha=<head>
  -->`, instead of as an issue comment.
  - A repo whose `review-settled` caller names `ocr` among its reviewers
    (e.g. `copilot-pull-request-reviewer|ocr`) is settled by that mark
    while it is the newest on the head and every thread is resolved.
  - Anything less (a file left unreviewed, a finding that failed to post,
    a failure) posts the summary as an issue comment saying it settles no
    review; re-run `/ocr`.
  - The review is posted with the workflow token, which starts no
    workflow, so `review-settled` must see it in the run the `/ocr`
    comment started: such a caller passes a `wait_seconds` on an `/ocr`
    comment that covers a whole run (the review job's limit is 9
    minutes; 900 is enough). A wait that ran out is re-evaluated by the
    next PR comment, or `gh workflow run review-settled.yml -f pr=<N>`.
- The run's job summary and its `ocr-review-record-<attempt>` artifact
  carry the run record: the design's Data Model, plus `backend` since
  `record_version` 2 (Issue#481, Key Decisions "Run record v2"). Pinned
  callers still write v1 records; `bin/ocr-review-stats` reads both.
- `ocr-result-<attempt>` is ocr's JSON result (`--audience agent`) for an
  LLM to act on.
- Causes and what to do:
  - `runner-tool-missing`: the runner lacks a host tool the review job
    needs; the detail names it. Add it to the runner image (next
    section).
  - `configuration`: run `bin/seed-ocr-review status`.
  - `credential`: Access refused the item's headers; check the item.
  - `gateway-down`: the laptop, its tunnel, the deadline proxy or the
    sandboxed ollama is down. On the laptop, `lmde status` says which; a
    sandboxed ollama that refuses to start (the G4 probe failed a row) is
    the commonest, and `docs/ops/ollama-gateway.md` has the diagnosis
    table.
  - `model-not-found`: the gateway does not serve that model.
  - `cold-model`: the model loaded for 6 minutes without answering; re-run.
  - `engine-error`: ocr failed, its result lacked the resolved range or the
    reviewed-file list, or the action's post counts were missing,
    unparseable or inconsistent with ocr's findings.
  - `reviewed-nothing`: reviewable files existed and ocr reviewed none.
- Trends across repos: `bin/ocr-review-stats` (read-only; `-p day|week|month`,
  `-d DAYS`, `-j`).

## Runner host tools

The review job's `Check the host tools` step (`bin/ocr-review host-tools`,
rule in `lib/ocr-review/host-tools.mjs`) runs before anything touches a
credential and logs which of `git`, `unzip`, `gpg` and `op` the runner
has (design Key Decisions, runner host tools; tds-utils Issue#446):

- `op` on PATH (the cf-pool image bakes in a pinned, verified one): it is
  used as is, and `Install the 1Password CLI` is skipped, so nothing is
  downloaded at run time.
- No `op` (a GitHub-hosted runner): the pinned
  `1password/install-cli-action` installs it, which needs `gpg` (its
  signature check) and `unzip`.
- `git` is needed either way (the upstream action and the verdict step).
- A tool the chosen path needs that is absent fails the run with cause
  `runner-tool-missing` and the tool as the detail, before credentials
  load. The fix is the runner image; signature verification is never
  dropped to get past it.

`node` and `npm` come from `setup-node` on every runner.

## Upstream at the pin

`alibaba/open-code-review` v1.12.13, commit
`fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`, with `ocr_version` 1.12.13.
Checked 2026-10-12 by reading `action.yml`,
`scripts/github-actions/post-review-comments.js`,
`cmd/opencodereview/output.go`, `internal/session/manifest.go` and
`internal/llm/client.go` at that commit.

- Inputs used: `llm_url`, `llm_auth_token`, `llm_model`,
  `llm_use_anthropic`, `llm_protocol`, `llm_auth_header`, `llm_extra_headers` (`K=V,K=V`),
  `llm_extra_body`, `ocr_version`, `pr_number`, `head_sha`, `base_ref`,
  `stream_progress`, `upload_artifacts`, `sticky_summary`,
  `checkpoint_range`, `incremental`, `resolve_outdated`.
- Telemetry has no input: it is off unless `OCR_ENABLE_TELEMETRY=1`; the
  workflow sets it to `0`, with `OCR_NO_UPDATE=1`.
- The resolved range and the per-file reviewed list are in ocr's JSON
  result: `manifest.input.resolved_base` / `resolved_head` and
  `manifest.coverage` (schema `ocr.run-manifest/v1`).
- Post outcomes are outputs as counts only: `comments_total`,
  `comments_inline`, `comments_failed`, `comments_routed`,
  `comments_skipped`, plus `summary_comment_url`. The verdict step reads
  the counts through its `env:`: `findings_failed` is `comments_failed`,
  `findings_posted` is `comments_inline` plus `comments_routed`, and a
  count that is empty, not an integer, or does not add up to ocr's
  findings is `engine-error`. `summary_comment_url` reaches the report job
  as the review job's `upstream_summary_url` output.
- Chat completions do not stream by default; `{"stream": true}` in
  `llm_extra_body` turns streaming on, and the workflow sets it.
- The action's default body, `{"thinking": {"type": "disabled"}}`, does
  not stop a thinking model reasoning on the gateway's ollama, and neither
  does `"think": false`: ollama's OpenAI-compatible API ignores both, and
  a thinking model spends its tokens reasoning before it answers
  (Issue#479). Only `"reasoning_effort": "none"` turns it off, so the
  workflow sends that too. The action's `llm_reasoning_effort` input does
  not accept `none`; an explicit key in `llm_extra_body` wins over it.
- `head_sha` and `base_ref` must be passed: on a dispatch or comment
  trigger the event carries no pull request, and the action would
  otherwise resolve an empty head.

## Choosing the backend: laptop, Cloudflare AI Gateway or Anthropic

Completions come from one of three backends (Issue#481 added the second):

- **`ollama-gateway`** -- the laptop's sandboxed ollama through the Ollama
  Gateway (`docs/ops/ollama-gateway.md`). The default, and free.
- **`cf-ai-gateway`** -- tds-internal's Cloudflare AI Gateway (the
  `personal` gateway, `ops/terraform/ai-gateway`): a Workers AI model
  through its OpenAI-compatible `/compat` endpoint, paid from the
  account's prepaid credits under the gateway's spend limit. An option for
  when the laptop is busy or off.
- **Workers AI models only** (`workers-ai/@cf/...`). ocr always sends an
  `Authorization` header, and the gateway forwards one to a third-party
  provider unchanged, so a third-party model (`openai/...`) would fail
  provider authentication; the Credentials step refuses one as
  `configuration`. On a Workers AI model that header carries the run
  token, which the gateway requires (Issue#489).
- **`anthropic`** -- the Anthropic API direct, on ocr's Anthropic
  protocol, paid from the Claude Console organization's credits (the
  monthly API credits of the owner's Max plan) under the key's workspace
  spend limit. Not routed through Cloudflare: the Authorization rule above
  would refuse a Claude model there, and Unified Billing would pay from
  Cloudflare credits instead of the Console's.

The owner's variable `OCR_BACKEND` chooses (unset is `ollama-gateway`); a
dispatch may override it with `-f backend=...`, as it may the model. A
`/ocr` comment always uses `OCR_BACKEND`. The summary comment and the run
record (v2) name the backend.

Each backend has its own three variables; only the chosen one's are read:

| Backend | Item | Base URL | Model |
|---|---|---|---|
| `ollama-gateway` | `OLLAMA_GATEWAY_OP_ITEM` | `OLLAMA_GATEWAY_URL` | `OLLAMA_GATEWAY_MODEL` |
| `cf-ai-gateway` | `CF_AI_GATEWAY_OP_ITEM` | `CF_AI_GATEWAY_URL` (the gateway base, `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>`) | `CF_AI_GATEWAY_MODEL` (a gateway model id; the owner's default is `workers-ai/@cf/deepseek-ai/deepseek-v4-pro-0813`) |
| `anthropic` | `ANTHROPIC_OP_ITEM` (an API Credential item; the key is its `credential` field) | `ANTHROPIC_URL` (the bare origin `https://api.anthropic.com`; ocr appends `/v1/messages`, so a path is refused as `configuration`) | `ANTHROPIC_MODEL` (a Claude model id, e.g. `claude-sonnet-5-5`) |

The Cloudflare backend has one more, optional variable:
`CF_AI_GATEWAY_REASONING`, sent as `reasoning_effort` (e.g. `none` turns
reasoning off on models that allow it -- DeepSeek V4 Pro, Kimi K2.6,
GLM-5.2; some, like Kimi K2.7 Code, always reason). Unset, the model's own
default applies, which is usually reasoning on. The owner's default
pairing is DeepSeek V4 Pro with `none` (2026-10-14).

The secret stays `OLLAMA_GATEWAY_OP_SA_TOKEN`: the same service account
reads every backend's item, so turning an option on adds no GitHub secret.

**What a Cloudflare request carries.** The run token from the item's
`password`, as `cf-aig-authorization: Bearer ...` (masked the moment it is
read); `cf-aig-metadata: {"tool":"ocr-review"}`, so the gateway's
per-tool spend rule partitions OCR from designomatic and the rest; and
`cf-aig-collect-log-payload: false`, so no diff is stored in the gateway's
logs. ocr always sends an `Authorization` bearer too, and on this backend
it is the same run token, masked: the gateway refuses a placeholder
bearer even for a Workers AI model (401 on every call, Issue#489), though
the probe -- which sends no `Authorization` -- passes. The request body is
streaming only: no ollama-specific field reaches a hosted model.

**Turning it on** (owner; the item and its token come from tds-internal,
whose registry names them -- this public repo does not):

```
gh variable set CF_AI_GATEWAY_OP_ITEM -o <org> --visibility selected --repos <repo,...> --body 'op://<vault>/<item>'
gh variable set CF_AI_GATEWAY_URL     -o <org> --visibility selected --repos <repo,...> --body 'https://gateway.ai.cloudflare.com/v1/<account>/<gateway>'
gh variable set CF_AI_GATEWAY_MODEL   -o <org> --visibility selected --repos <repo,...> --body 'workers-ai/@cf/deepseek-ai/deepseek-v4-pro-0813'
gh variable set CF_AI_GATEWAY_REASONING -o <org> --visibility selected --repos <repo,...> --body none
# then either per run: -f backend=cf-ai-gateway, or for every run:
gh variable set OCR_BACKEND           -o <org> --visibility selected --repos <repo,...> --body cf-ai-gateway
```

On a user account (9atatimer) set them per repository (`-R <owner>/<repo>`
instead of `-o`), as the seeder does for the Ollama variables. Unsetting
`OCR_BACKEND` is the way back to the laptop.

**Its answers** (the probe reads them; nothing is retried, since there is
no cold model and the gateway applies its own retry policy):

| Probe answer | Cause |
|---|---|
| a chat completion | ready |
| 401, 403 | `credential` |
| 402 (credits exhausted) | `budget` |
| 429 (a spend limit, or the unified-billing request rate of 200 a minute: the status cannot tell which) | `limited` |
| any other 4xx | `model-not-found` |
| 5xx, or no answer | `gateway-down` |

The pool's 10-minute ceiling is the limit on either backend, by decision
(design Key Decisions, a review's length; Issue#478): a PR that does not
finish in it is not reviewed, and the run fails at the job timeout as
`unexpected` (Known gaps). A hosted model is far faster than the laptop,
so it is the likelier backend to fit it.

Measured on the first Cloudflare run (2026-10-14, run 38539937733, DeepSeek
V4 Pro with `reasoning_effort` none): 7 code files, ocr's own elapsed time
8m24s, 17 gateway calls, 115k tokens in and 25k out, $0.24. The review
job took 8m56s against its `timeout-minutes: 9` (set under the pool's
ceiling), 4 seconds to spare. At about $0.03 and over a minute a file, a
PR any larger than seven files is likely to hit the job's timeout long
before the spend cap.

**What an Anthropic request carries.** The key from the item's
`credential` field (masked the moment it is read) as `llm_auth_token`,
which `llm_auth_header: x-api-key` puts on `x-api-key`: the API refuses
the key as an `Authorization` bearer. ocr's Anthropic client does not
stream and sends `anthropic-version` itself; the body adds nothing
(`{}`), and `CF_AI_GATEWAY_REASONING` is never read. The probe posts the
smallest message to `<ANTHROPIC_URL>/v1/messages`. Spend is capped by the
key's Console workspace spend limit and the organization's credit
balance, not by anything here.

**Turning it on** (owner; the item comes from tds-internal, whose registry
names it):

```
gh variable set ANTHROPIC_OP_ITEM -o <org> --visibility selected --repos <repo,...> --body 'op://<vault>/<item>'
gh variable set ANTHROPIC_URL     -o <org> --visibility selected --repos <repo,...> --body 'https://api.anthropic.com'
gh variable set ANTHROPIC_MODEL   -o <org> --visibility selected --repos <repo,...> --body 'claude-sonnet-5-5'
# then either per run: -f backend=anthropic, or for every run:
gh variable set OCR_BACKEND       -o <org> --visibility selected --repos <repo,...> --body anthropic
```

**Its answers** (nothing is retried by the probe; ocr's own client retries
overload during the review):

| Probe answer | Cause |
|---|---|
| a message | ready |
| 401, 403 | `credential` |
| 402, or 400 naming the credit balance | `budget` |
| 400 naming usage limits (a workspace or organization spend limit), 429 | `limited` |
| 404 | `model-not-found` |
| any other 4xx | `unexpected` |
| 5xx (529 is overload), or no answer | `gateway-down` |

## Comparing models (the bake-off)

Which model `OLLAMA_GATEWAY_MODEL` should name is measured, not guessed
(Issue#468): `.github/workflows/ocr-bakeoff.yml` reruns real past reviews
-- diffs Copilot or Codex reviewed, scored against the inline findings on
them that triage accepted -- through the same gateway, ocr pin and
settings as OCR on Demand, with nothing posted anywhere.

- **The cases** are `lib/ocr-bakeoff/cases.json`: each is a repository, the
  range a bot saw (`base` = merge-base of the PR's base and the reviewed
  commit, `head` = the reviewed commit) and the accepted findings on it.
  The first set comes from template-tools'
  `docs/ops/review-calibration/` survey; code files only, because ocr
  skips Markdown. A case must be in a public repository: the run job
  checks it out with the caller's token.
- **The caller** is `docs/ocr-bakeoff-caller.yml`, copied into a
  repository that already runs OCR on Demand (it needs the same secret and
  variables) with both SHAs set to one tds-utils commit, like the OCR on
  Demand caller.
- **Run it** from that repository; `models` is one per line or comma,
  `cases` a comma list of case ids (empty for all):

  ```
  gh workflow run ocr-bakeoff-caller.yml -R <owner>/<repo> \
      -f models='qwen3.6:latest,<other model>' -f cases=''
  ```

  Every model must already be in the laptop's store (`ollama pull` on the
  everyday instance). Jobs run one at a time, model by model, so the first
  case of each model carries its cold load; each job holds the production
  budget (8 minutes for probe plus review), so a review production would
  time out on times out here too.
- **Read it** in the `collate` job's summary: per model, runs, failures by
  cause (`timeout`, `probe-failed`, `engine-error`, `no-record`), located
  k of n, total findings, the cold load and the median review time.
  "Located" is mechanical -- a finding on the same file within 10 lines of
  an accepted one. Whether it names the same defect, and whether the
  findings that locate nothing are real, is judged from the
  `ocr-bakeoff-results` artifact (every finding with its text and quoted
  code); post the judged table on the Issue that asked the question.
- **Choosing** stays the owner's: the result recommends, the owner sets
  `OLLAMA_GATEWAY_MODEL`.

## Known gaps (reported, not worked around)

- **No per-finding post status at the pin.** The action reports post
  outcomes only as counts, so the verdict judges by counts and our summary
  cannot list the findings that failed to post; upstream's summary names
  them, and ours links it. A later pin that exposes per-finding status can
  restore the stricter contract (design Key Decisions, option A).
- **Upstream's summary comment cannot be turned off at the pin.** It stays
  beside ours (sticky, so one per PR), by ruling.
- **The proxy's status codes are mirrored by hand.** `GATEWAY_STATUS` in
  `lib/ocr-review/gateway.mjs` holds 503 (ollama down) and 507 Model Not
  Ready (the deadline answer, the one retryable code) as the LMDE proxy
  layer's `ollama-gateway` route serves them; a change there must change
  it too.
- **A timed-out job cannot name its step.** The token holds no `actions`
  scope (design permissions), so a timeout reads `unexpected` with
  "(no step failed: job timeout or runner lost)".
- **The probe and the review share 9 minutes** under the pool's 10-minute
  container ceiling. The probe starts no attempt after 6 minutes, but the
  last one can run to the gateway's 90 s deadline, so a cold model that
  never answers costs about 7.5 minutes. The pilot's green run took 65 s
  for the whole review job, with the model's files in the laptop's OS
  cache; a load from a cold OS cache is unmeasured (task-046).

---

## Changing OCR on Demand

For whoever changes the `/ocr` machinery itself: the workflow, `bin/ocr-review`,
`lib/ocr-review/`, the seeder, and the pins. Later rulings live in the
design record's Key Decisions log; the umbrella issue is Issue#363.

### Where things live

| Piece | Path | Notes |
|---|---|---|
| Reusable workflow | `.github/workflows/ocr-review.yml` | Thin YAML: three jobs (authorize, review, report), each step calling `bin/ocr-review <step>` |
| Step commands | `bin/ocr-review` | The composition root: env in, GitHub/git/op/fetch calls, step outputs out. Exports every `run*` flow and `gitIn` for tests |
| Decisions | `lib/ocr-review/*.mjs` | Pure: authorize, gateway probe classification, verdict, record and summary, host tools, reactions, stats |
| Caller template | `docs/ocr-review-caller.yml` | Copied verbatim into adopting repos; two SHAs pin it |
| Seeder, stats | `bin/seed-ocr-review`, `bin/ocr-review-stats` | Human-run; `status` reports each adopter's pin |
| Bake-off | `.github/workflows/ocr-bakeoff.yml`, `bin/ocr-bakeoff`, `lib/ocr-bakeoff/` (rules and `cases.json`), `docs/ocr-bakeoff-caller.yml`, `test/ocr_bakeoff.test.mjs` | Reuses `bin/ocr-review`'s credentials and probe steps; its ocr settings (`OCR_SETTINGS`, `configArgs`, `reviewArgs`) mirror `ocr-review.yml` and the pinned action by hand, so a change to one is a change to both |
| Tests | `test/ocr_review_*.test.mjs`, `test/smoketest_ocr_review.sh`, `test/smoketest_seed_ocr_review.sh` | The smoketest is the list of node suites; a new suite is added there |
| Runner image | tds-internal `services/ci-runner-pool/Dockerfile` | The pool's host tools (git, gnupg, unzip, a pinned and verified `op`); its `test/wiring.test.ts` lists them |
| Gateway | `lmde/components/ollama-gateway/`, `lmde/components/proxy-layer/`; tds-internal `ops/terraform/ollama-gateway/` | The deadline status (507) and Host rewrite live in the route; operating the laptop side is `docs/ops/ollama-gateway.md` |
| Backends | `lib/ocr-review/gateway.mjs` (`BACKENDS`, the per-backend variables, profiles, credential shapes and probe readings); tds-internal `ops/terraform/ai-gateway/` for Cloudflare AI Gateway | A new backend is a profile (API suffix, probe path, protocol, auth header, body), a variable set, a credential reader and a probe reading there, plus its env lines in both workflows |

### Invariants a change must keep

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

### Making a change

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
  "Read the result" above. Stats count causes by name and need no edit.
- A new job output must be declared on the job and read by the report
  through `needs:`; the workflow test asserts the wiring.
- A design-level change appends one Key Decisions row to the design
  record, citing its issue or ruling. Never edit the body.
- Run, all green, before committing:
  - `bash test/smoketest_ocr_review.sh`
  - `/bin/bash test/smoketest_seed_ocr_review.sh`
  - `/bin/bash test/syntax_sweep.sh`
  - `shellcheck` on any changed shell

### Proving it live

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

### Changing a pinned dependency

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

### Review

- Self-review every PR with a fresh-context sub-agent (the self-review
  skill) and post the epilogue on the PR.
- Codex reviews only when the owner summons it; an agent never posts
  `@codex review`. Copilot is out of quota.

### Lessons from the pilot

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
