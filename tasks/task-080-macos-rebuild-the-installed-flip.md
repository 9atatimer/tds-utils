---
id: task-080
kind: task
title: "macOS: rebuild the installed flip-monitor bundle from the merged checkout"
created: 2026-11-14
---

The Desktop bundle was hand-built during the prototype and hardcodes an absolute path.
`macos/apps/flip-monitor/build --dest ~/Desktop --force` replaces it in place and keeps the Dock tile valid.
Machine step on the owner's laptop; design: `docs/design/MACOS-APPS.DESIGN.md`.
