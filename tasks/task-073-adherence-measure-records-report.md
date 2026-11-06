---
id: task-073
kind: bug
title: "adherence: adhere measure never records its report"
created: 2026-11-06
issue: 681
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`adhere measure` computes and prints a report but never writes it to the
report store (`cli/main.py:233-247`), against D:135/G16. Done when a test
shows the command writes its report under the report identity and still
prints and exits as today.
