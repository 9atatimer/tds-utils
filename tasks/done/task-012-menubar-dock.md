---
id: task-012
kind: task
title: chores: menu-bar monitor and Dock app
created: 2026-09-14
blocked_by: [task-011]
implements: docs/design/CHORES.DESIGN.md
---

`bin/chores-monitor` (rumps, launchd plist, launcher script) mirroring `bin/skills-drift-monitor` file-for-file, reading `chores status --json`; icon shape+color rule from the design; menu opens the TUI in Terminal. `macos/apps/chores/` via `mkmacapp`. Add the files to `packages/lmde.pkg` or a new `packages/chores.pkg`.
