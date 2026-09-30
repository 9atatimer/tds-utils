---
id: task-030
kind: task
title: "dynomark MVP: writer marker -- a second host configured writer detects the marker and refuses to file"
created: 2026-09-27
blocked_by: [task-027]
implements: docs/design/DYNOMARK.DESIGN.md
---

Key Decision "Two writers", MVP half: the writer leaves a marker in the
owned tree; a host whose `HostRole` is `writer` that sees another host's
marker refuses every write-producing use case with a distinct result and
surfaces it in the settings page. Changing writers is explicit: clear the
marker on the old host, then flip the flag on the new one. RED tests on
the domain rule with the tree fake first.
