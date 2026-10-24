---
id: task-063
kind: task
title: "adherence: the declaration in force through ReviewPort"
created: 2026-10-24
issue: 597
blocked_by: [task-062]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`ReviewPort` with `github_reviews` (standard library over the REST API,
the job's `GITHUB_TOKEN`), `no_reviews` (`Unknown`) and the fake, and
`domain/declaration`'s walk: the newest landed revision of
`adherence.toml` whose landing a code owner of that path approved, on a
commit whose declaration equals the landed one, never the PR's author;
in `ci` an unreadable review or a landing with no PR is skipped and a
walk that finds nothing judges the repository undeclared. RED first:

- An unapproved declaration is not in force
- An author's approval is refused
- An unreadable edit is a notice

Done when the fake drives every branch of the walk and `github_reviews`
passes the contract suite against recorded REST fixtures, never the live
API, in the unit tier.
