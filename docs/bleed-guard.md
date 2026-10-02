# bleed-guard -- runbook

Keeps private strings out of a public repo (issue #366).

Code:

- `bin/bleed-guard` -- the checker.
- `git-hooks/template/hooks/pre-commit` -- runs it before the branch guard.
- `bin/install-git-hook-templates` -- links it to `~/.local/bin/bleed-guard`
  and sets `bleedguard.checkerPath`.
- `test/smoketest_bleed_guard.sh` -- the test suite (runs in CI).

---

## What it does

A repo opts in with a committed `PUBLIC.REPO` file at its root; tds-utils
carries one. In such a repo every commit's staged additions -- added lines,
and the names of added or renamed files -- are matched against a private
denylist. Any hit refuses the commit and is reported as `file:line` plus
the line of the denylist entry it matched. The matched text is never
printed, so the refusal cannot itself leak into a log or transcript.

It runs on every branch, trunk and detached HEAD included. Removing a
string is never refused: only additions are checked.

## The denylist

It is private by construction -- publishing the list would be the leak --
so it lives in the private repo, not here. Resolution order:

- `$TDS_BLEED_DENYLIST`
- `git config bleedguard.denylist` (tilde-expanded)
- `~/workplace/tds-internal/ops/bleed-denylist`

Format: one fixed string per line, matched case-insensitively. Blank lines
and lines starting with `#` are ignored; surrounding whitespace is trimmed.
Keep entries specific -- an account id, a vault or item name, a bucket, a
gateway path. A short common word blocks every commit that uses it.

No denylist (a machine without the private checkout) is a one-line skip.

## Daily use

```
bleed-guard            # check the index, as the hook does
bleed-guard --tree     # audit every tracked file (pre-existing leaks)
```

Opt out: `TDS_BLEED_GUARD=0` for one command, or
`git config bleedguard.enabled false`. `git commit --no-verify` skips every
pre-commit gate; a leak committed that way is still in public history once
pushed.

## Limits

- Strings only. Prose that describes private contents (which backends exist,
  how a private module is laid out) is reviewer judgment.
- A clone keeps the hook it was cloned with. An existing clone picks the
  bleed guard up only when the template's `pre-commit` is copied into its
  `.git/hooks/`.
- CI has no denylist, so CI runs only the hermetic suite, never a scan.
