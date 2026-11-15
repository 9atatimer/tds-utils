---
id: task-093
kind: task
title: "Rotate the GitHub Packages PAT in ~/.npmrc and stop keeping it in plaintext"
created: 2026-11-14
---

A read-only PAT sits in cleartext in `~/.npmrc` and was emitted twice into a Claude transcript (2026-05-11 audit).
Revoke and replace it; hydrate `${GITHUB_PACKAGES_TOKEN}` at call time from `gh auth token` through `npm`, `pnpm`, `yarn` and `npx` wrappers in `bash/dot.bashrc.d/` or `macos/`, so no secret is on disk.
