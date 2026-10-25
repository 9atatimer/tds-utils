---
id: task-062
kind: task
title: "adherence: judge_change -- provenance, removed findings, verdict, exemptions, Declared"
created: 2026-10-24
issue: 596
blocked_by: [task-061]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`judge_change` by the architecture's signature, which takes `reviews:
ReviewPort`, so this task also defines `ReviewPort`'s protocol, its
`no_reviews` adapter (`Unknown`, under which the landed declaration
stands) and its fake; `github_reviews` and the approval walk are
task-063. With it: the `git` adapter's `changed` (created, deleted,
renamed) and `history`, `ReportStore` with its file cache keyed by report
identity and its fake, `record_report`, and the domain's provenance
with file and definition renames, the removed-finding rule, the verdict
in the design's order, exempt findings counting as neither, widening for
created units, and the Declared quality's change-level checks. RED
first, one row per commit, in this order:

- A change that raises is raised
- A change that lowers is lowered
- A fixed flaw stays fixed
- An introduced flaw lowers
- An existing flaw does not block
- A break on an untouched unit is introduced
- A rename introduces nothing
- Deleting clean code moves nothing
- Deleting a flawed unit moves nothing
- An undeclared new unit is found
- A widening is honored
- A narrowed record is found
- A record is read with its code
- A missing design record is reported
- A newly covered unit's flaws are existing
- A change cannot narrow its own declaration
- An added exemption is inert for its change
- An exemption carries its reason
- An unmeasurable base is inconclusive
- A missing record on both sides is not inconclusive
- A rule check that errors is coverage
- An unreadable file is coverage
- A suite that cannot run says so
- A report persists

The rows whose Then is a judged check's doing are task-064's. `cli/main.py`
gains the `judge --base --head` command on the JSON presenter. Done when
`bin/adhere judge --base --head` over two fixture revisions prints the
verdict the design's table gives.
