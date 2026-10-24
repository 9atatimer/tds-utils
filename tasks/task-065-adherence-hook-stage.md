---
id: task-065
kind: task
title: "adherence: the hook stage -- judge_bounded, WorkerPort and the deadline through every port"
created: 2026-10-24
issue: 592
blocked_by: [task-062]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`Deadline` threaded through every deadline-bound port method, each
adapter capping its work at the smaller of `Limits.analyzer_bound` and
the time remaining and returning `TimedOut`; `WorkerPort` with
`process_worker` (a child process and a pipe of finished checks, ended
at the deadline) and `inline_worker` (the fake, scriptable to end after
N checks); `judge_bounded` and `assemble_partial`; the `hook` stage in
`container.py` (staged index as head, `HEAD` as base, `no_judge` from
task-058, `no_reviews` from task-062, `process_worker`), `bin/adhere
judge --staged`, and the hook's exit mapping (inconclusive exits zero).
RED first:

- The hook ends within its bound (the fake worker ends after one check)
- CI out of time is coverage (the same path with the `ci` deadline)
- every deadline-bound port's contract suite: a passed deadline returns
  `TimedOut` (the suites for `DecisionPort` and `ReviewPort` run against
  their fakes and `no_judge` and `no_reviews`; the decide and
  github_reviews adapters join them in task-066)

Done when a fixture analyzer that sleeps past the bound is ended and the
commit proceeds with the unfinished checks as coverage. The
`naatm-hooks` stage that calls this is template-tools Issue#1023.
