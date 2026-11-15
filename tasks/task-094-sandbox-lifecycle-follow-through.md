---
id: task-094
kind: task
title: "Sandbox lifecycle follow-through"
created: 2026-11-14
implements: docs/design/SANDBOX-LIFECYCLE.DESIGN.md
---

Approach A shipped and was verified in a fresh session (2026-08-14). Open from it, each in its own issue:
- tds-utils Issue#193: CI job that runs a real `lmde acquire`.
- Issue#139: map the seed and authority split onto the Codex, Jules and Copilot wrappers.
- Issue#219: Approach B spike, spawn-time acquisition for ast-mcp.
- Issue#188 and template-tools#428: git-mirror pin parity; sandbox-qol publish or drop.
- Issue#194: laptop `servers.txt` still pins ast-mcp 0.3.1; needs a laptop session.
- Issue#226: vendored `acquire.sh` byte identity is enforced by nothing.
- Issue#224: `sandbox/README.md` documents the pre-naatm-sandbox install.
- Issue#228: three dead links to `CLAI.DESIGN.md`.
- template-base#66 and #68, template-tools#412.
The acceptance probe (template-tools#420) arrived in a fresh session without a cache rebuild.
