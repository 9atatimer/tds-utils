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
`DECIDE_GATEWAY_TOKEN`. The hosted judge has been bound in CI since
2026-11-07 (tds-utils PR#722), but no CI job runs the floor yet
(Issue#622): a question's wording or a set's labels change, and nothing
asks the judge until a person runs it by hand. Grow the set from real
flaws found and real false findings before moving a threshold, and
report each question and each class apart.

## Wording a question

The first run against the hosted judge (2026-11-07, Issue#728 and
Issue#733) found five of nine questions answering labelled examples
confidently wrong. Clef applied each question literally. It counted a
workflow's calls into a store as the workflow's own effects, read a
verbosity flag as a business decision, and passed a test that asserted
only `is not None`. Saying what counts fixed all five (tds-utils PR#734
and PR#738), but the first fix keyed each carve-out on names and shapes:
"a configuration flag", a "...Record" suffix, "wherever it is written".
That is a steering channel, because the author of the code under
judgement chooses the names. It also contradicted labelled examples:
strict mode is a configuration flag that decides validity, and
`LedgerEntry` is a domain term.

- **Judge by substance.** Say what the code decides, what the types
  mean, or what a unit reads, never what a thing is called.
- **Name the exclusions by what they do.** For example: only changes
  how output is shown; only checks whether a call succeeded, to report
  its failure.
- **Check each new wording against every example of both labels, by
  reading.** The floor only says nothing is confidently wrong.
- **Run the floor three times against the hosted judge** before trusting
  a change: the judge is probabilistic. The command is `uv run pytest
  tests/integration/test_eval_floor.py` from `adherence/`, with
  `DECIDE_GATEWAY_URL` and `DECIDE_GATEWAY_TOKEN` read from the judge's
  item; add `-k <question id>` for one question.
- **Know where the wording lives.** A question's wording is in
  `adherence/src/adherence/domain/questions.py`, and its id, kind and
  options must not change. If a new wording changes how an example
  should be read, update that example's `note` in `<question>.jsonl`
  in the same change. A changed label is a decision about the example,
  not a fix to the wording.
