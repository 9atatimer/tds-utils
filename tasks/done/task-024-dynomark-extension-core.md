---
id: task-024
kind: task
title: "dynomark phase 2: extension domain and use cases over fakes (search_local, apply_batch, record_move, transport calls)"
created: 2026-09-27
blocked_by: [task-022]
implements: docs/design/DYNOMARK.DESIGN.md
---

The extension runtime's core, in TypeScript, driven by the Behaviors rows
that name extension-side ports. Fakes from task-022; no browser API is
imported outside `adapters/`.

Rows, one RED then one GREEN commit each:

1. Content is captured from the open tab (`capture` with the tab fake):
   `source` `tab`, text non-empty; no matching tab -> `source` `none`.
2. A save is submitted (`submit_save`): two submissions of one node ->
   the transport fake holds one request id.
3. Tier-1 search (`search_local`): every title match precedes every
   non-title match; frecency orders within a tier; owned-item bonus; a
   10,000-entry index completes under the Goal 4 budget in the test
   runner (a perf assertion, skipped on a slow CI runner rather than
   flaky).
4. Tier-2 search is requested (`search_remote`) only under
   `tier2_min_hits` / `tier2_min_score`; hits carry `tier` `corpus`.
5. A batch is applied (`apply_batch`): snapshot read first, operations in
   order, `APPLIED` with a node id per operation.
6. A batch resumes after termination: cursor at operation 3 of 5 ->
   operations 1-3 not repeated.
7. A batch fails midway: `PARTIAL` with the applied prefix.
8. Operations are path-idempotent: create-if-absent at path,
   move-if-not-already-there, against the tree fake.
9. A receipt is delivered (`ack_batch`) twice -> recorded once.
10. The local index is synced (`sync_index`): one row per entry, <= 512
    bytes.
11. A user move becomes feedback (`record_move`): origin `user` on the
    writer -> feedback; origin `extension` or role `reader` -> none. The
    adapter sets `origin` from operations it itself issued; the domain
    rule is tested with both origins.
12. Ownership boundary in the extension: a batch touching a path outside
    `OwnedRoots` without a `DiffItem` reference is `REJECTED` before the
    first operation.
13. Learning checkpoint.

Acceptance: a mechanical test asserts no `chrome.*` / `browser.*`
reference outside `src/adapters/`; the omnibox and chat pages are not in
this task (task-026 wires the omnibox; chat is MVP, task-028).
