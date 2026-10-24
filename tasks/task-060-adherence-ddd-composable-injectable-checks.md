---
id: task-060
kind: task
title: "adherence: the Domain-driven, Composable and Injectable rule checks"
created: 2026-10-24
issue: 592
blocked_by: [task-059]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
The rule parts of the three qualities, RED first against `measure`:

- A foreign noun is found
- An anemic type is found (rule part)
- A foreign write is found
- A wire format in a signature is found
- A nested function is found
- A helper that takes a port is found
- A port taken by position is found
- A self-wired use case is found
- A reach is found

`Vocabulary` carries what counts as a vendor, an environment read, a
model id and a wire format per language; it ships with defaults and the
declaration may extend it. Done when the three scores print over the
fixture and each check's finding names what the design's row says it
names.
