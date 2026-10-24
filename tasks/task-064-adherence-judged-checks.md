---
id: task-064
kind: task
title: "adherence: the judged checks through the decide client"
created: 2026-10-24
issue: 595
blocked_by: [task-061]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`DecisionPort` with the `decide` adapter (the door's address on the
laptop, the hosted configuration in CI, `docs/ops/decide.md`), `no_judge`
and the fake; `Question`, `Schema`, `Decision` and `ThresholdPolicy` with
one entry per question id, by kind (binary, choice, score); questions
batched per unit within `Limits.judged_budget`; and the labelled set
under `adherence/evals/` for the nine question ids (`two_jobs`,
`does_io`, `same_concept`, `scattered_policy`, `invariant_broken`,
`rules_elsewhere`, `then_asserted`, `implemented`, `hand_rolled`). RED
first, with canned decisions behind the fake at, above and below each
threshold and inside the band:

- A judged check answers with a confidence
- A unit doing two jobs is found; A port in a rule is found (judged part);
  Two spellings of one concept are found; A hidden policy is found; A
  write that breaks an invariant is found; An anemic type is found
  (judged part); A test that skips the Then is found; An unfinished unit
  is found; A hand-rolled primitive is found
- An abstention is inconclusive; An unavailable judge is inconclusive,
  never raised; An exhausted judged-check budget is inconclusive
- The judge is given data

Thresholds are chosen from the labelled set and its floor goes in CI
(the decision-models skill, Evaluation before adoption); the first
thresholds may be provisional with the set small, said so in the test.
Done when the real-model contract run is marked integration and the unit
tier never loads weights or calls the network.
