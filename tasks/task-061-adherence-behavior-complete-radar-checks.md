---
id: task-061
kind: task
title: "adherence: the Behavior-driven, Complete and Radar-true rule checks"
created: 2026-10-24
issue: 592
blocked_by: [task-060]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`ComplexityPort` (lizard) and `DuplicationPort` (jscpd) with their fakes,
the radar read through `RecordsPort`, and the remaining target-level rule
checks, RED first against `measure`:

- A behavior with no kept test is found
- A test that cannot fail is found
- A test past the surface is found
- A stub is found
- A function over the complexity ceiling is found
- A clone over the duplication ceiling is found
- A disallowed dependency is found
- A radar entry in the core is found

Radar gate: the lizard and jscpd rows must be on `lmde/TECH_RADAR.md`
first (Issue#599). Done when every target-level rule check in the
design's Qualities table has a GREEN test and `bin/adhere measure` prints
eight qualities' findings over the fixture; the Declared quality's two
checks are change-level and land with task-062, and the judged checks
read as coverage missing until task-064.
