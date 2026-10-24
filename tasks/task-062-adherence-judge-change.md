---
id: task-062
kind: task
title: "adherence: judge_change -- compared score, provenance, verdict, tickets, floors, Declared"
created: 2026-10-24
issue: 596
blocked_by: [task-061]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`judge_change` by the architecture's signature, the `git` adapter's
`changed` (created, deleted, renamed) and `history`, `ReportStore` with
its file cache keyed by report identity and its fake, and the domain's
`ComparedScore`, provenance with file and definition renames, the verdict
in the design's order, floors, drop tickets marked used, widening for
created units, and the Declared quality. RED first, one row per commit,
in this order:

- A change that raises is raised; held; lowered; An introduced flaw lowers;
  An existing flaw does not block; A break on an untouched unit is
  introduced; A rename introduces nothing; Deleting clean code moves nothing
- An undeclared new unit is found; A widening is honored; A narrowed record
  is found; A record is read with its code; A newly covered unit's flaws
  are existing; A change cannot narrow its own declaration; An added
  exemption is inert for its change; An exemption carries its reason
- A floor holds; An unreached floor does not bind
- A drop ticket accepts a fall; survives a moving base; covers no second
  fall; An unmarked ticket covers nothing; A drop ticket is shown until
  regained
- An unmeasurable base is inconclusive; A missing record on both sides is
  not inconclusive; A rule check that errors is coverage; An unreadable
  file is coverage; A suite that cannot run says so; The same finding
  everywhere; A report persists (`record_report`)

The judged rows wait for task-064. Done when `bin/adhere judge --base
--head` over two fixture revisions prints the verdict the design's table
gives.
