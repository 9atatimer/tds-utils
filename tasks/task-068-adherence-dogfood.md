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
file; an adherence job in `dist-ci.yml` under a `changed-scopes.sh` scope
for `adherence/`, in `gate`'s `needs`. RED first: a case in
`test/smoketest_changed_scopes.sh` that a change under `adherence/`
selects the new scope and a change elsewhere does not (that script's
own header says a wrong rule skips a suite and leaves `gate` green),
then the scope and the job. Done when the first run is green with no
floor, and a throwaway branch that moves a port import into
`adherence/domain/` is lowered by its own gate, then reverted.
