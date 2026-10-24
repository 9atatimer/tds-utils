---
id: task-066
kind: task
title: "adherence: the CLI surface -- stages, presenters and SARIF"
created: 2026-10-24
issue: 598
blocked_by: [task-062]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`cli/main.py`: `measure`, `judge`, `explain`, `declaration check`;
`container.py` binding the four stages (`laptop`, `hook`, `ci`, `cloud`)
from one flag; presenters for the terminal (control characters and ANSI
stripped from evidence), JSON, SARIF 2.1.0 (one rule per check, one
result per finding, identity as the fingerprint, provenance and kind as
properties, notices as notifications) and the PR job summary (markdown
escaped). RED first against the presenters as pure functions over a
`Report` value, then the entry point's exit-status mapping per stage.
Done when `bin/adhere judge --format sarif` over the fixture validates
against the SARIF 2.1.0 schema and `bin/adhere --help` lists the stages.
