---
id: task-029
kind: task
title: "dynomark MVP: TreeDiff -- propose_diff (audit, rebuild), recorded acceptance, accept_diff_item batches"
created: 2026-09-27
blocked_by: [task-027]
implements: docs/design/DYNOMARK.DESIGN.md
---

Behaviors rows: a diff is proposed (items exist, no batch); a diff item is
accepted only with `accepted_at` set; an accepted audit item may cross the
`OwnedRoots` boundary and its inverse carries the same item reference;
pinned folders immune to rebuild and audit moves. Merge rules stay
undefined (design Open Question 1); suggest-only, one item at a time.
