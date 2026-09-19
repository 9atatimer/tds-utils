---
id: task-020
kind: task
title: "tmux-herd: prune idle tmux sessions, rename the rest <agent>@<owner/repo>=<branch>+<slug>"
created: 2026-09-19
blocked_by: [task-021]
implements: docs/design/TMUX-HERD.DESIGN.md
---

Build `bin/tmux-herd` against the design, test-first: the classifier and
the namer are pure functions over fixture text (`list-panes` lines plus a
`pid -> ppid,comm,args` table), so `test/smoketest_tmux_herd.sh` drives
them with fixtures and a stub `tmux`/`git` on PATH, never a live server.

Gates before code: the design is DRAFT until Todd marks it APPROVED (the
design skill); the naming grammar and the log-hoarder rename gate are the
two places a reader should check first. Blocked on task-021 because until
log-hoarder keys log dirs on `#{session_id}`, every piped session is
`SKIP (log-hoarder pipe open)` and the tool cannot deliver its second
goal on the machine it exists for.

Copilot's three review rounds on PR #305 are already folded into the
design (12 findings, all resolved on the threads); do not re-derive them.
