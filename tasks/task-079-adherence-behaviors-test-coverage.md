---
id: task-079
kind: bug
title: "adherence: Behaviors rows with no test, and a never-run test that skips"
created: 2026-11-06
issue: 692
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
Behaviors rows with no test: the judged-finding version of "A change that
lowers is lowered", the verdict halves of the unavailable-judge and
exhausted-budget rows, Language half of "A missing design record is
reported", and the four places of "The same finding everywhere". The
never-run test (`tests/integration/test_repository_code_never_run.py:32`)
points at `adherence/node_modules/.bin/jscpd`, not
`adherence/node/node_modules/.bin/jscpd`, so it always skips, and never
covers ast-grep or dependency-cruiser. Done when each row has a test that
fails without the behavior and the never-run test runs, unskipped, for all
three analyzers in CI.
