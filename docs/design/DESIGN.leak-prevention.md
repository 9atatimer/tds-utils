# Leak Prevention and Stale Data Audit (Issue #131)

> **Status:** DRAFT  
> **Date:** 2026-07-11  
> **Authors:** Antigravity  
> **Depends on:** [clone-audit.md](../clone-audit.md)

---

## Overview

This design outlines Phase 0 cleanup of stale, machine-generated directories/files (emacs Semantic parse cache, emacs auto-save-list markers, macOS .DS_Store) and the Prevention phase introducing automated detection of stale directories, legacy hostnames, and RFC1918 private IPs in `bin/clone-audit`.

---

## Goals

1. **Clean HEAD Tracking** -- Untrack and remove legacy auto-save-list, semanticdb cache, and .DS_Store files from the repository's active state.
2. **Prevent Recurrence** -- Add a `BLEED-HAZARD` check to `bin/clone-audit` that flags stale directories/caches and leak hazards.
3. **Scrub Hostnames** -- Remove legacy hostnames from author comments in Emacs files.
4. **Soften Wording** -- Modify colloquial language in `tds-shell-mode.el`.

---

## Non-Goals

- **destructive history rewrite** -- History scrubbing (Phase 1) is human-only and off-sandbox due to shallow clones and git-filter-repo requirements.
- **forks or clone cleanup** -- Collaborator clone and fork remediation (Phase 2) are administrative human tasks.

---

## Architecture Overview

```
+------------------+     +--------------------------+
|  git clone / check  |---->| post-checkout hook       |
+------------------+     +--------------------------+
                                     |
                                     v
+------------------+     +--------------------------+
|  scan results    |<----| bin/clone-audit          |
|  (BLEED-HAZARD)  |     | (with BLEED-HAZARD scan) |
+------------------+     +--------------------------+
```

---

## Design

### Phase 0 Cleanup

This component untracks files at HEAD and scrubs hostname leaks in active files.

| File/Path | Action | Detail |
|-----------|--------|--------|
| `emacs/dot.emacs.d/semanticdb/` | git rm --cached | Untrack all cache files in semanticdb |
| `emacs/dot.emacs.d/auto-save-list/` | git rm --cached | Untrack all auto-save-list files |
| `local/.DS_Store` | git rm --cached | Untrack .DS_Store file |
| `.gitignore` | edit | Add `emacs/dot.emacs.d/semanticdb/` |
| `emacs/dot.emacs.d/elisp/tds-pants.el` | edit | Scrub legacy hostname in line 5 |
| `emacs/dot.emacs.d/elisp/tds-bootstrap.el` | edit | Scrub legacy hostname in line 5 |
| `emacs/dot.emacs.d/elisp/tds-shell-mode.el` | edit | Soften phrasing in line 5 |

### Prevention: bin/clone-audit Detector

We add a new `scan_bleed_hazard` function in `bin/clone-audit` under a new threat model tag: `BLEED-HAZARD`.

The scanner performs three check phases:

1. **Directory check**: Scans for directories named `semanticdb` or `auto-save-list` in the workspace.
2. **File check**: Scans regular files under ROOT (pruning build/VCS dirs) for base names containing `.DS_Store` or `.cache` (if path includes `emacs/`).
3. **Identifier/IP leak check**: Scans filenames and file contents for legacy hostnames or RFC1918 private IPs using standard regexes.

#### Regex Patterns for Leak Check

- **Legacy Hostnames**: twttr\.net|twitter\.com|tw-[a-zA-Z0-9-]+\.local|mbp-[a-zA-Z0-9-]+\.local
- **RFC1918 Private IPs**:
  - 10\.[0-9]+\.[0-9]+\.[0-9]+
  - 172\.(1[6-9]|2[0-9]|3[0-1])\.[0-9]+\.[0-9]+
  - 192\.168\.[0-9]+\.[0-9]+

---

## Security Considerations

- **Secret/leak detection** -- Adding this detector to the daily clone-audit prevents future accidental commits of hostnames and private network IP identifiers.
- **Handling of findings** -- No full paths of sensitive legacy files are printed in commit messages or public reviews.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Leak detection scope | Combined checks (path + filename + content) | Ensures robust prevention of both stale file tracking and data leakage. |
| Bash regex execution | Pipe to `grep -qE` | Avoids compatibility issues with `=~` syntax in older macOS bash 3.2. |

---

## Open Questions

None.

---

## Rejections

- **Direct rewrite in sandbox** -- Force-pushing is strictly forbidden by `AGENT.md`, and the sandbox is shallow so it cannot rewrite deep history.
- **Overly generic IP detector** -- Scanning for all IP formats would flag public IPs (CDNs, package registry hosts), leading to high false positives.

---

## Related Documents

- [clone-audit.md](../clone-audit.md) -- Operational runbook.
