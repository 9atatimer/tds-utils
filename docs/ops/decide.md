# decide -- runbook

`bin/decide` asks a decision model typed questions about a state -- yes/no
(`noul`), pick-one (`choice`), rubric (`score`) -- and prints the answer as
probabilities, never generated text.

- Client: `bin/decide`; decisions in `lib/decide/` (schema, backend,
  answers, failure, args).
- Tests: `test/smoketest_decide.sh` runs the node suites
  (`test/decide_*.test.mjs`, fakes only) and two real-binary checks. CI
  runs it in `dist-ci.yml`'s smoketests job.
- When to reach for a decision model at all: the `decision-models` skill.

---

## Setup on the laptop

The hosted backend is Clef on Workers AI through the fleet's Cloudflare AI
Gateway. Its infrastructure is tds-internal `ops/terraform/ai-gateway`; the
item names and ids are in tds-internal, not here.

```
export DECIDE_GATEWAY_URL='https://gateway.ai.cloudflare.com/v1/<account>/<gateway>'
export DECIDE_GATEWAY_OP_ITEM='op://<vault>/<item>'
bin/decide probe
```

- `DECIDE_GATEWAY_URL` is the gateway base recorded in the note of the
  gateway's run-token item, `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>`;
  a trailing slash is stripped. `decide` takes the account and gateway
  ids from it and posts to Cloudflare's REST route,
  `https://api.cloudflare.com/client/v4/accounts/<account>/ai/run/@cf/cloudflare/<model>`,
  with the token on `Authorization` and the gateway on
  `cf-aig-gateway-id`, so the gateway's spend rules and log still apply.
  It does not use the gateway's own `workers-ai` route: with the gateway
  on Unified Billing that route answers 401 for every Workers AI model
  (tds-utils Issue#512, 2026-10-15), and Cloudflare documents Workers AI
  through a gateway on the REST route only.
- `DECIDE_GATEWAY_OP_ITEM` is that item's `op://` reference. `decide` runs
  `op read "<item>/password"` once per invocation, so 1Password must be
  unlocked and the CLI signed in. Failure -> `config` (exit 2).

## Setup in a cloud agent session

No 1Password there. Put two environment secrets on the session's
environment:

- `DECIDE_GATEWAY_URL` -- as above.
- `DECIDE_GATEWAY_TOKEN` -- the dedicated decide token that tds-internal
  `ops/terraform/ai-gateway` mints for this consumer. Never the laptop's
  run token.

`DECIDE_GATEWAY_TOKEN` wins when both it and `DECIDE_GATEWAY_OP_ITEM` are
set. The token is never printed; any error message carrying it is
redacted.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `DECIDE_BACKEND` | `cf-ai-gateway` | or `systemone` (a SystemOne server, below) |
| `DECIDE_GATEWAY_URL` | -- | gateway base (cf-ai-gateway) |
| `DECIDE_GATEWAY_TOKEN` | -- | literal run token (cf-ai-gateway) |
| `DECIDE_GATEWAY_OP_ITEM` | -- | `op://<vault>/<item>` holding the token in `password` |
| `DECIDE_URL` | -- | SystemOne base; `decide` posts to `${DECIDE_URL}/v1/systemone` |
| `DECIDE_MODEL` | `clef` | `clef` or `clef-flash` on cf-ai-gateway; any `^[A-Za-z0-9._-]+$` on systemone. `--model` wins |
| `DECIDE_TOOL` | `decide` | the gateway's per-tool tag, `^[a-z0-9-]{1,40}$`. `--tool` wins |
| `DECIDE_TIMEOUT_MS` | `60000` | per request |
| `DECIDE_LOG_PAYLOAD` | unset | `1` lets the gateway log request and response bodies; otherwise every request says `cf-aig-collect-log-payload: false` |

## Usage

```
decide run   [--model M] [--tool T] [--jsonl] [--concurrency N] [--file PATH]
decide probe [--model M]
decide --help
```

One record, from a file or stdin:

```
cat > ticket.json <<'EOF'
{"id": "ticket-7",
 "state": "My invoice charged me twice this month.",
 "questions": {
   "spam":    {"type": "noul",   "instructions": "Is this message spam?"},
   "team":    {"type": "choice", "instructions": "Which team should handle it?",
               "criteria": {"billing": "charges, invoices, refunds", "technical": "bugs, outages"}},
   "urgency": {"type": "score",  "instructions": "How urgent is it?",
               "criteria": ["can wait a week", "this week", "today", "drop everything"]}}}
EOF
bin/decide run --tool triage --file ticket.json
```

A batch, one record per line, answers in input order, 8 in flight:

```
bin/decide run --jsonl --concurrency 8 --tool triage --file tickets.jsonl > decisions.jsonl
```

Connectivity and latency: `bin/decide probe` -> `{"ok": true, "model":
"clef", "latency_ms": 212}`.

- `id` is yours: copied to the output, never sent to the model.
- Validated before any network call: a non-blank `state` (string or
  JSON); 1-64 questions; ids `^[A-Za-z0-9_.-]{1,100}$`; `instructions` a
  non-empty string; `choice` criteria an object of 2-255
  `{option: description}`; `score` criteria an array of 2-10 level
  descriptions, lowest first; `noul` takes no criteria; at most 4 `images`,
  each a `data:` URL or a `{content_type, base64}` object.
  Anything else -> `rejected` (exit 3), no request sent.
- `--jsonl`: one output line per non-blank input line. A bad line or a
  failed request is a failure line, not the end of the batch. Exit 0 when
  every line succeeded, else the exit code of the first failure in input
  order.
- Retries: one, after 2 s, on a network error, HTTP 502/503/504, or a
  Workers AI capacity 429 ("Capacity temporarily exceeded"); one, after
  10 s, on the gateway's request-rate 429 ("rate limited"). Never on a
  timeout, any other 429 (a spend rule holds until its window resets), or
  any other status.

## The answer

```
{"id": "ticket-7", "ok": true, "model": "clef", "backend": "cf-ai-gateway",
 "latency_ms": 212, "usage": {...},
 "answers": {
   "spam":    {"type": "noul", "p_true": 0.02, "vendor_confidence": null, "calibrated": true},
   "team":    {"type": "choice", "probabilities": {"billing": 0.96, "technical": 0.04},
               "top": "billing", "vendor_confidence": 0.91, "calibrated": true},
   "urgency": {"type": "score", "levels": 4, "probabilities": [0.1, 0.55, 0.3, 0.05],
               "expected": 1.3, "unit": 0.433, "top": 1, "vendor_confidence": 0.43, "calibrated": true}},
 "raw": {...the backend's answer, unwrapped...}}
```

- `score`: `probabilities` lowest -> highest, one per level asked;
  `expected` = sum(i * p_i), computed here; `unit` = expected/(levels-1);
  `top` = the most likely level, or null when the backend sent only a
  score and no probabilities (rounding an expectation does not find the
  mode). If the vendor's own `score` differs from
  `expected` by more than 0.01 it rides along as `vendor_expected`.
- `choice`: `top` is the argmax here; a disagreeing vendor `choice` rides
  along as `vendor_choice`.
- `noul`: `p_true`, the probability of yes.
- `calibrated: false` means no full distribution: the probabilities did
  not sum to 1 within 0.98-1.02 (kept as received), or the answer was a
  label only (`probabilities` or `p_true` is `null`).
- `raw` is kept because the vendor's answer shapes are thinly documented
  (next section).

## Failure classes

Failures still print JSON on stdout: `{"id": ..., "ok": false, "error":
{"class", "message", "status"}}` (probe: `{"ok": false, "model", "error"}`).

| Exit | Class | Means | Do |
|---|---|---|---|
| 2 | `config` | missing or bad environment or flags; `op read` failed; HTTP 404 (no such route or model) | fix the setup above |
| 3 | `rejected` | the record failed local validation, or HTTP 400/413/422 (and other 4xx) | fix the record; the message carries the vendor's reason |
| 4 | `unavailable` | network error, timeout, HTTP 5xx, 402, or 429. A 429 names its kind: "Workers AI capacity is temporarily exceeded", "the gateway's request-rate limit", or otherwise "spend limit or rate limit" | capacity: rerun later; request rate: lower `--concurrency`; otherwise check the gateway's per-tool spend rule |
| 5 | `auth` | HTTP 401/403: the token was refused | check the token or item |
| 6 | `malformed` | a 2xx that is not JSON, lacks a question, or has an answer that cannot be read | look at the vendor's answer; see "Answer shapes" |

## Cost

Clef costs $0.24 per million input tokens; output is free (Cloudflare's
Workers AI pricing page, 2026-10-15). Every request stamps
`cf-aig-metadata: {"tool":"<tool>"}`, so the gateway's per-tool spend rule
caps each consumer separately: give every caller its own `--tool`.

## Gotchas

- **Threshold on the probabilities, never on `vendor_confidence`.** The
  vendor's `confidence` is undocumented and is not the top probability.
  It is passed through and nothing here reads it.
- **`expected` can fall between levels.** 1.5 on a four-level rubric means
  the mass is split, not that there is a level 1.5. Act on `probabilities`
  or `top` when you need a level.
- **Clef has no abstain option.** It always distributes the mass over the
  options you gave. Abstention ("not sure enough, route elsewhere") is the
  caller's threshold policy, decided in the caller's code.
- **Vague instructions give near-0.5 answers.** A probability near the
  middle often means the question is ambiguous, not that the state is.
  Sharpen `instructions` and `criteria` before reading it as uncertainty.
- **Images take one of two shapes**, as Cloudflare's Clef schema has
  them: a `data:image/<png|jpeg|webp>;base64,...` URL, or
  `{"content_type": "image/png", "base64": "..."}`. At most 4. Raw base64
  and remote URLs are refused locally.
- **Answer shapes are thinly documented.** The Workers AI docs show no
  sample response. `decide` reads choice and score as the Hugging Face card
  describes them, score probabilities keyed by level index, by legend label
  or as an array, and noul as Cloudflare's reference SystemOne code answers
  it, `{"type": "noul", "noul": p}` (Issue#513), or from a bare number,
  `{probability}`, `{probabilities: {true, false}}` or `{value}`. A shape
  outside those is `malformed`; `raw` in a success shows what actually came
  back.
- **The vendor's machine-readable sources outrank its prose.** Both shape
  defects found after release came from trusting prose: the noul answer
  shape was in the model repository's `joint_schema_model.py`, not the
  card's text (Issue#513), and the two image shapes were in Cloudflare's
  published model schema (`cloudflare-docs`
  `src/content/workers-ai-models/clef.json`), not the Workers AI page.
  Check a request or answer shape against those two first.
- **A 401 (exit 5) on the REST route means the token lacks Workers AI
  Read.** The REST route checks the token itself, and only tds-internal
  `ops/terraform/ai-gateway` grants that permission, so a run token minted
  before that change is refused until the module is applied. (The 401 that
  opened Issue#512 was a different thing: the gateway's own `workers-ai`
  route refuses every Workers AI model on Unified Billing, whatever the
  token carries, which is why `decide` no longer uses it.)
- **The state leaves the machine** on cf-ai-gateway. Payload logging is off
  by default; it is still a hosted model.
- **Local backend.** `DECIDE_BACKEND=systemone` with `DECIDE_URL` posts the
  same body to a SystemOne server (SGLang's `/v1/systemone`) with no auth:
  the shape the decision arena will serve
  (`docs/concepts/decision-arena/CONCEPT.md`). Clef's local inference is
  tested on CUDA only; Apple silicon is unproven.
