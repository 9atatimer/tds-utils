---
id: task-021
kind: bug
title: "log-hoarder keys pane log dirs on the mutable session name; a rename strands the open pipe"
created: 2026-09-19
issue: 307
implements: docs/design/LOG-HOARDER.DESIGN.md
---

See the issue: `bin/tmux_logging.sh` builds the path from `#S` at pipe
open and `bin/tmux_shepherd.sh` sweeps by name, so `rename-session`
leaves the pipe writing under a name the sweep treats as dead. Evidence
and done-criteria are on issue #307. The fix is re-derived from
`LOG-HOARDER.DESIGN.md` when picked up; a RED test in
`test/smoketest_log_hoarder.sh` (rename, then sweep, then assert the log
is still active) comes first.
