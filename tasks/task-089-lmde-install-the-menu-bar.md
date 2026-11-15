---
id: task-089
kind: task
title: "LMDE: install the menu-bar monitors through `tds-install -S`"
created: 2026-11-14
---

`lmde-sync-monitor` and `skills-drift-monitor` do not survive a reboot through the ENV-DISTRIBUTION pipeline: `SERVICES=` in `packages/lmde.pkg` (`bin/tds-install -S`) has never run on this machine.
`skills-drift-monitor` is loaded by a manual copy into `~/Library/LaunchAgents`; `lmde-sync-monitor`'s plist still hardcodes the dev-checkout path.
Formalize both through the pipeline.
