---
id: task-068
kind: task
title: "adherence: this repository measures the suite in its own gate"
created: 2026-10-24
issue: 600
blocked_by: []
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

Progress (2026-11-06): the declaration, the self-declaration test, the
`changed-scopes.sh` arm and the `adherence-judge` job landed first, ahead
of tasks 063-067, as an advisory job outside `gate`'s `needs` (the engine
measures nothing until a repository is declared, so the route's value
began here). The reusable workflow of task-067 replaced the inline job,
and `adherence-judge` joined `gate`'s `needs` after its first green run
(run 42298026212, 2026-11-06, the declaration counted in force under the
Q11 ruling), both in tds-utils PR#675. The throwaway-branch proof ran
2026-11-06 against master 4fdc114 in the `ci` stage, locally with the
job's variables set rather than as a pull request (the owner's one-PR
rule): the declaration read in force (merged by code owner 9atatimer) and
a domain module importing `adherence.adapters.fakes` read `lowered`
(Hexagonal / Arrow, exit 1). The same engine and stage run in the gate.
