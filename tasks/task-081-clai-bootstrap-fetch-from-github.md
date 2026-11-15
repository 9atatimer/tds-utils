---
id: task-081
kind: task
title: "clai bootstrap: fetch from GitHub Packages, not the blocked release-asset path"
created: 2026-11-14
issue: 101
---

`sandbox/provision.sh` still fetches the clai wheel over `api.github.com` release assets, which the Claude web proxy blocks.
Rework `bootstrap_clai` to `npm install` `@nine-at-a-time-media/clai` from GitHub Packages, as the ast-mcp fix did: classic `read:packages` token, ephemeral mode-600 `.npmrc`, fail-open. See Issue#101.
