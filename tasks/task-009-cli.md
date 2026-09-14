---
id: task-009
kind: task
title: chores: CLI surface
created: 2026-09-14
blocked_by: [task-008]
implements: docs/design/CHORES.DESIGN.md
---

Click commands: `list`, `validate`, `status [--json]`, `runs [--chore] [--since] [--status] [--json]`, `show <run-id> [--json|--transcript|--stdout|--stderr|--errors]`, `run <name>`, `tick`, `pause [reason]`, `resume [chore]`, `kill <run-id>`, `notify <text> | --dismiss <id>`. One `status()` application query feeds `status` and later surfaces. Tested through `CliRunner` with fakes; snapshot the table output.
