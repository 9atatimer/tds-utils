# chores UX -- clean-room proposal

> **Phase:** 1 -- CONCEPT material. Non-binding; nothing here is a design
> record or an approved spec.
> **Date:** 2026-09-27

A designer AI was given `chores-ux-brief.md` and nothing else -- no code,
no screenshots, no description of the TUI and menu bar already built
(tasks 011, 012). What it returned is kept here verbatim so a later design
pass can compare it against the as-built surfaces.

| File | What it is |
|---|---|
| `chores-ux-brief.md` | the prompt: brief, domain reference, constraints, sample snapshot, the user stories |
| `chores-ux-design.md` | the designer's answer: wireframes, attention model, CLI output, story traceability |
| `chores-manual.md` | use and wiring manual for every surface (app, TUI, menu bar, Dock, CLI) |
| `Chores App.dc.html` | interactive prototype of a Mac app surface |
| `Chores Prototype.dc.html` | interactive prototype of the TUI, menu-bar item and Dock tile |
| `export/Chores App.html` | self-contained export of the app prototype; opens offline |
| `support.js`, `_ds/` | runtime and design-system assets the two `.dc.html` files load |

The `.dc.html` files fetch React and Phosphor icons from unpkg, so they
need a network connection; the export does not.

Beyond the brief: the proposal adds a windowed Mac app beside the TUI,
with a parity table (`chores-manual.md` 6.14). Todd settled that direction
on 2026-09-28 (CONCEPT.md Notes). CHORES.DESIGN.md lists a windowed GUI as
a Non-Goal, so adopting it is a design amendment, not drift.
