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
file; and task-067's `adherence.yml` joining `gate`'s `needs` after its
one green run here, as the architecture's Rollout row says (the
`adherence` unit-test job task-056 put in `dist-ci.yml` is unchanged;
nothing judges a PR twice). RED first: a test that `load_declaration`
through `RepositoryPort` at `HEAD` of this repository returns the layers,
runtime, records and radar the file declares, then a case in
`test/smoketest_changed_scopes.sh` that a change to `adherence.toml`
alone selects the `adherence` scope, made GREEN by its arm in
`changed-scopes.sh`. Done when the first run is green
on its own base, and a throwaway branch that moves a port import into
`adherence/domain/` is lowered by its own gate, then reverted.
