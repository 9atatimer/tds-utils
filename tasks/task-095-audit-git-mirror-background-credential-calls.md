---
id: task-095
kind: task
title: "Audit git-mirror background credential calls"
created: 2026-11-14
---

Background scripts that call the `git-mirror` credential process must fail gracefully or warn, not block, when run by coding agents in mirrored repositories.
