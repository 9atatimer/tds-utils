---
id: task-055
kind: bug
title: "dynomark: the frozen body and contract text no longer describe the MVP as merged"
created: 2026-10-16
issue: 544
implements: docs/design/DYNOMARK.DESIGN.md
---

The owner amends the design body for each row of issue #544, or rejects
it. Three fixes land whichever way the body goes:

- the contract v2 README's "A connection keeps the role its hello gave
  it" (line 154);
- a repeat `hello` on a connection `rebind` demoted still answers
  `role: writer` (`dynomark/daemon/src/dynomark_daemon/adapters/dispatch.py:486`;
  RED test first);
- three code headers cite a design section that is gone.

The body rows that a task-054 ruling touches wait on that ruling; the
three fixes above do not.
