---
id: task-001
kind: task
title: chores: package scaffold and toolchain gates
created: 2026-09-14
implements: docs/design/CHORES.DESIGN.md
---

Create `chores/` (uv project, `src/chores/`, `tests/unit/`) with ruff, strict mypy and pytest configured per the style-python skill, `bin/chores` wrapper mirroring `bin/goldfish`, and a `chores-ci` job in `.github/workflows/dist-ci.yml` running lint, types and tests. First RED: `chores --version` through Click's `CliRunner`.
