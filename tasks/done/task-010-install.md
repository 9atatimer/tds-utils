---
id: task-010
kind: task
title: chores: scheduler install
created: 2026-09-14
blocked_by: [task-009]
implements: docs/design/CHORES.DESIGN.md
---

`chores install [--dry-run]` writes `~/Library/LaunchAgents/com.tds.chores.tick.plist` (`StartInterval` 60, bare `chores tick` via the PATH mould of `com.tds.skills-drift-monitor.plist`) on macOS or a systemd user timer on Linux, and `uninstall` removes it; `status` reports not-installed / stale. Templates are data files; the writer is an adapter with a fake filesystem in tests.
