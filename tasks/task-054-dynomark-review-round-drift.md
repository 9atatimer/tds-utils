---
id: task-054
kind: bug
title: "dynomark: rule on and fix the drift the MVP review rounds left"
created: 2026-10-16
issue: 538
implements: docs/design/DYNOMARK.DESIGN.md
---

The retrospective of tds-utils PR#535 found five broken design rules,
each a decision for the owner: issue #538 (block rules stricter than the
address policy), #539 (`capture_window` against the durable-state rule),
#540 (an unanswered save filed elsewhere is never ingested), #541 (a
lock fallback lands in the parent) and #542 (a same-parent move is
dropped in the extension). It also found behaviour the design never
specified, issue #543.

Each ruling is a Key Decisions row citing its issue. A ruling that
changes code gets a RED test first (law 5). Paths are in each issue.
