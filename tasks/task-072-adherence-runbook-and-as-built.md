---
id: task-072
kind: task
title: "adherence: runbook, LMDE contract entry, and the as-built at first release"
created: 2026-10-24
issue: 602
blocked_by: [task-068]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`docs/ops/adhere.md` (install, stages, the hook switch, the CI caller,
the declaration format with a worked example, exemptions,
the ledger, kill switches, rollback, gotchas); `lmde/LMDE.md` listing
`adhere` under the contract beside `decide`; and at the first release,
`docs/arch/adherence/ARCHITECTURE.md` with every tuned value per stage
(thresholds, bands, ceilings, bounds, budget) and a row in
`docs/arch/ARCHITECTURE.md`'s inventory. The release is R3 (release
skill): `references/readiness.md` answered, rollback rehearsed on a
throwaway repository. Then the retrospective (phase 8): the drift walk
against both frozen records.

The as-built also records what the nested-declarations leg built that
neither record names, listed in Issue#714: the glob escaping of a
declaring directory, the conflict scan bounded to nested subtrees, one
tree listing and merge per judgement, the percent-encoded declaration
path in the contents URL, and the notices for deleted, created and
unlisted declaration files. The runbook's declaration example is a
per-package file (template-tools PR#1062) beside the root one.
