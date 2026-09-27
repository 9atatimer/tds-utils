---
id: task-031
kind: task
title: "dynomark MVP: background-tab capture on the writer for saves made on a reader device or phone"
created: 2026-09-27
blocked_by: [task-027]
implements: docs/design/DYNOMARK.DESIGN.md
---

Future Considerations "Background-tab capture": a third `ContentSourcePort`
adapter on the writer's extension opens the saved URL in a background tab
in a non-focused window, captures as from any tab, closes it. Writer chain
becomes matching tab -> background tab -> fetch, behind a setting
(default on). Recovers logged-in content for saves made elsewhere because
the writer's browser is usually signed in to the same sites. Adds a
`source` value to the glossary via a Key Decisions append, not a body
edit.
