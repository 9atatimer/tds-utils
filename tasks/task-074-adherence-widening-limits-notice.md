---
id: task-074
kind: bug
title: "adherence: no notice when a change widens the declaration or edits [limits]"
created: 2026-11-06
issue: 682
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
A head declaration that widens for created units, or edits `[limits]`,
yields no notice (`domain/checks/declared.py:489-493`), against D:232-233.
The `[limits]` half needs task-075 to parse the table. Done when tests show
each case yields a notice naming it, in every presenter.
