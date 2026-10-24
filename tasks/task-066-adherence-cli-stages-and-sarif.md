---
id: task-066
kind: task
title: "adherence: the CLI surface -- the laptop, ci and cloud stages, presenters and SARIF"
created: 2026-10-24
issue: 598
blocked_by: [task-063, task-064, task-065]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`container.py` binding the `laptop`, `ci` and `cloud` stages (the `hook`
stage is task-065's): the decide adapter hosted or through the door,
`github_reviews` in `ci`, `no_reviews` elsewhere, `file_store` outside
`ci` (`ExplanationPort` is task-071's, which binds it); `cli/main.py`
choosing the stage from one flag and mapping the verdict to the exit
status per stage; the presenters for the terminal (control characters and ANSI
stripped from evidence), SARIF 2.1.0 (one rule per check, one result per
finding, identity as the fingerprint, provenance and kind as properties,
notices as notifications) and the PR job summary (markdown escaped). RED
first against the presenters as pure functions over a `Report` value,
then the entry point's exit-status mapping per stage, then the decide
and github_reviews adapters joining the deadline contract suite. Done
when `bin/adhere judge --format sarif` over the fixture validates
against the SARIF 2.1.0 schema and `bin/adhere --help` lists the four
stages.
