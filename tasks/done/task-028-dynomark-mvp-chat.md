---
id: task-028
kind: task
title: "dynomark MVP: grounded chat -- ask use case, chat page, Ask fall-through in the omnibox"
created: 2026-09-27
blocked_by: [task-027]
implements: docs/design/DYNOMARK.DESIGN.md
---

Behaviors rows: a question is answered with citations (only retrieved
identities become `Citation`s); an out-of-corpus URL is marked
`external`; a placement is explained (`explain_placement`). Chat page is a
view over the background context, not a composition root; conversation
state lives in the page. The omnibox gains the always-last `Ask: <query>`
row. Route: RED tests with fake completion first, then the page.
