# The labelled set

The examples the judged checks' thresholds are chosen from
(docs/design/ARCHITECTURE.ARCH-ADHERENCE.md, Facts and judgements told
apart; the decision-models skill, Evaluation before adoption). One file
per question id, keyed on the ids and options the domain fixes in
`src/adherence/domain/questions.py`; renaming an id or an option is a
migration of this set and of the threshold policy.

## Format

`<question id>.jsonl`: one JSON object per line.

| Field | Meaning |
|---|---|
| `id` | The example's own id, `<question id>-<n>`, unique across the set |
| `label` | The answer the question should get: `yes` or `no` for a binary question, a level for `then_asserted` (`not asserted`, `partly`, `fully`), a library or `none` for `hand_rolled` |
| `text` | The unit's text as a judged check sends it: a function or type's header and body |
| `context` | The further data the question reads, as the check builds it (empty when it reads none) |
| `note` | Why the example carries its label, in a line |
| `options` | `hand_rolled` only: the radar's Adopt entries offered; `none` is added by the question |

Each file holds a handful of examples, at least two whose label is a
finding (a binary question's failing answer, `not asserted`, a library)
and two that are not. `tests/unit/test_evals.py` checks the format;
`tests/integration/test_eval_floor.py` runs the set through the real
judge under the shipped thresholds.

## What it supports

Six examples per question prove the plumbing and catch a judge that is
confidently wrong; they support no rate. The shipped thresholds
(`container.SHIPPED_THRESHOLDS`) are provisional and conservative until
the set grows: a binary finding needs 0.9, the score and the choice 0.85,
with a wide abstention band below. The floor is that no example is
answered confidently wrong. It runs wherever a judge is configured:
`DECIDE_URL` on a laptop, or the hosted `DECIDE_GATEWAY_URL` and
`DECIDE_GATEWAY_TOKEN`. It becomes the gate's once the hosted judge is
bound in CI (task-067; DESIGN.ARCH-ADHERENCE.md Q4). Until then no CI
job runs it, and the shipped thresholds are checked against the labelled
set by running it by hand. Grow the set from real flaws found and real
false findings before moving a threshold, and report each question and
each class apart.
