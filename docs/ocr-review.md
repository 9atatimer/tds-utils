# OCR on Demand -- runbook

Runs Alibaba's Open Code Review (`ocr`) over a pull request when you ask,
in any repo of 9atatimer or Nine-At-A-Time-Media, with completions from the
laptop's model through the Ollama Gateway.

- Design: `docs/design/OCR-ON-DEMAND.DESIGN.md` (APPROVED; the authority).
- Reusable workflow: `.github/workflows/ocr-review.yml`.
- Caller template: `docs/ocr-review-caller.yml`.
- Step commands: `bin/ocr-review`; decisions in `lib/ocr-review/`.
- Seeder: `bin/seed-ocr-review`. Stats: `bin/ocr-review-stats`.
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
  could not tell.
- `seed` needs 1Password unlocked. It pipes the service-account token from
  `op read` into `gh secret set`, never as an argument, and sets
  `OLLAMA_GATEWAY_OP_ITEM`, `OLLAMA_GATEWAY_URL`
  (the gateway base URL from tds-internal's credential registry, passed with `-u`) and `OLLAMA_GATEWAY_MODEL`
  (`qwen3.6:latest`). On 9atatimer (no org tier) it writes each consumer
  repo; on Nine-At-A-Time-Media it writes org secrets and variables whose
  repo selection it widens, never narrows.
- Re-run `seed` after a new adopter and after a rotation.

## Trigger a review

- Dispatch (write access; an agent holding Todd's token may use it, Key
  Decisions Q3):

  ```
  gh workflow run ocr-review-caller.yml -R <owner>/<repo> -f pr=<N>
  gh workflow run ocr-review-caller.yml -R <owner>/<repo> -f pr=<N> -f model=<model>
  ```

- Comment: a PR comment whose body starts with `/ocr`, from an OWNER,
  MEMBER or COLLABORATOR. The comment path always uses the configured
  model. Any other comment is skipped and leaves nothing behind.
- Fork PRs fail with cause `fork`; nothing reads the secret for them.

## Read the result

- A PR carries two summary comments (owner ruling "option A"):
  - this workflow's, one per run: the outcome and, on failure, the cause
    (`unexpected` also names the failing job and step); on success the
    reviewed-file counts, the action's post counts and every reviewable
    file ocr did not review. `pr-not-open` posts none.
  - upstream's own, sticky (updated in place each run): the findings that
    could not be anchored inline and each finding that failed to post.
    Ours links it whenever the action reports its URL.
- The run's job summary and its `ocr-review-record-<attempt>` artifact
  carry the run record (`record_version` 1, the design's Data Model).
- `ocr-result-<attempt>` is ocr's JSON result (`--audience agent`) for an
  LLM to act on.
- Causes and what to do:
  - `configuration`: run `bin/seed-ocr-review status`.
  - `credential`: Access refused the item's headers; check the item.
  - `gateway-down`: the laptop, its tunnel, the deadline proxy or the
    sandboxed ollama is down.
  - `model-not-found`: the gateway does not serve that model.
  - `cold-model`: the model loaded for 6 minutes without answering; re-run.
  - `engine-error`: ocr failed, its result lacked the resolved range or the
    reviewed-file list, or the action's post counts were missing,
    unparseable or inconsistent with ocr's findings.
  - `reviewed-nothing`: reviewable files existed and ocr reviewed none.
- Trends across repos: `bin/ocr-review-stats` (read-only; `-p day|week|month`,
  `-d DAYS`, `-j`).

## Upstream at the pin

`alibaba/open-code-review` v1.12.13, commit
`fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`, with `ocr_version` 1.12.13.
Checked 2026-10-12 by reading `action.yml`,
`scripts/github-actions/post-review-comments.js`,
`cmd/opencodereview/output.go`, `internal/session/manifest.go` and
`internal/llm/client.go` at that commit.

- Inputs used: `llm_url`, `llm_auth_token`, `llm_model`,
  `llm_use_anthropic`, `llm_protocol`, `llm_extra_headers` (`K=V,K=V`),
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
- `head_sha` and `base_ref` must be passed: on a dispatch or comment
  trigger the event carries no pull request, and the action would
  otherwise resolve an empty head.

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
  container ceiling; a 6-minute cold load leaves about 3 for the review.
  The pilot (task-051) measures it.
