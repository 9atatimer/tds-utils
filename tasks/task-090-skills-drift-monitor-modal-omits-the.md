---
id: task-090
kind: bug
title: "skills-drift-monitor modal omits the stale-check note when the last verified state was drift"
created: 2026-11-14
issue: 309
implements: docs/design/LMDE.DESIGN.md
---

`show_status_modal` tests `self.drift_lines` first, so a last-verified drift state followed by `last_unknown` shows the drift detail with nothing saying the reading may be stale; only the green branch carries the note.
Same seam as Issue#276: a `show_status_modal` that yields a testable message instead of driving `rumps` directly.
