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
the radar read through `RecordsPort`, and the remaining rule checks, RED
first against `measure`:

- A behavior with no kept test is found
- A test that cannot fail is found
- A test past the surface is found
- A stub is found
- A function over the complexity ceiling is found
- A clone over the duplication ceiling is found
- A disallowed dependency is found
- A radar entry in the core is found

The lizard and jscpd rows must be on `lmde/TECH_RADAR.md` first
(Issue#599). Done when every rule check in the design's Qualities table
has a GREEN test and `bin/adhere measure` prints all nine scores over the
fixture, with the judged checks as coverage missing.
