---
id: task-068
kind: task
title: "adherence: this repository measures the suite in its own gate"
created: 2026-10-24
issue: 600
blocked_by: [task-067]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`adherence.toml` at this repository's root declaring `adherence/` by
layer, the `adhere` runtime, the two Adherence records as its design
records and `lmde/TECH_RADAR.md` as its radar; a CODEOWNERS line for the
file; and `bin/adhere judge` added to the `adherence` job task-056 put
in `dist-ci.yml`, so the engine's own PRs are judged. RED first: a test
that `load_declaration` over this repository's root returns the layers,
runtime, records and radar the file declares, then a case in
`test/smoketest_changed_scopes.sh` that a change to `adherence.toml`
alone selects the `adherence` scope. Done when the first run is green
with no floor, and a throwaway branch that moves a port import into
`adherence/domain/` is lowered by its own gate, then reverted.
