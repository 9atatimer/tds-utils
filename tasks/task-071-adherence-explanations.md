---
id: task-071
kind: task
title: "adherence: explanations through an ExplanationPort that can act on nothing"
created: 2026-10-24
issue: 603
blocked_by: [task-066]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`explain` by the architecture's signature and the `explain` command;
`ExplanationPort` with `no_explainer` (the default), `claude_cli` (print
mode, every tool disallowed, the repository outside its working
directory, an allowlisted environment) and the fake; the port's contract
suite asserting the adapter reads no repository file and spawns nothing
but the model's own process with those flags. RED first:

- An explanation changes nothing
- A disagreeing explanation shows both
- The explainer can act on nothing

Radar gate: the Claude CLI row the architecture proposes must be on
`lmde/TECH_RADAR.md` first (Issue#599); the fleet radar's `claude-cli
provider` row is a different use. Last in the order; the MVP ships
without it.
