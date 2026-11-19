# tds-public -- runbook

Publishes allow-listed parts of tds-utils to two public repositories:
`9atatimer/workflows` (the shared CI workflows and their tool code) and
`9atatimer/tds-utils-public` (a mirror of the environment). Design:
`docs/design/DESIGN.PUBLIC-RELEASE.md` (Issue#825).

Code:

- `bin/tds-public` -- the publisher.
- `lib/bleed-match.sh` -- the denylist matcher it shares with `bin/bleed-guard`.
- `publish/workflows.allow`, `publish/tds-utils-public.allow` -- what each
  target may receive.
- `test/smoketest_tds_public.sh` -- the test suite (runs in CI).

---

## What it is and when it runs

For one target and one released commit, `tds-public` selects the files that
the target's allow-list names, checks them against the refusal rules below,
and pushes one snapshot commit to the target. It never rewrites a file and
never sends tds-utils history.

It runs as a step of `bin/tds-post-release`, after `bin/tds-release` has
moved `release`. You can also run it by hand.

## Commands

```zsh
tds-public -n <target> <sha>    # preview: print the selection and every refusal, push nothing
tds-public <target> <sha>       # publish
```

- `<target>` is `workflows` or `tds-utils-public`.
- `<sha>` must be the head of `release`. Any other commit is refused.
- Exit 0: published, or nothing to publish. Exit 1: refused, or the push
  failed. Exit 2: usage error (missing argument, unknown target or flag).

Run the preview before a release that changes an allow-list or a published
file. It lists every refusal, not only the first.

## The allow-lists

Each target has `publish/<target>.allow`. One path or glob per line,
relative to the repository root. `#` starts a comment. There is no negation.
A file that no line names is not published.

To publish a new path, add a line in a PR and release. The owner approves
the PR as for any change. A new file in tds-utils stays private until a line
names it.

An allow-list with no path lines publishes nothing: the tool says so, exits
0 and does not contact the remote. `publish/tds-utils-public.allow` is empty
on purpose until the owner decides its contents (Issue#833).

## Refusals

Any one refusal stops the whole publication. Nothing is pushed and the exit
is 1. The tool prints each refusal as:

```
tds-public: refused: <rule>: <path>[:<line>] -- <reason>
```

It never prints the text that matched the denylist.

| Rule | Meaning | What to do |
|------|---------|------------|
| `no-denylist` | No denylist was found, or the file named for it is missing. The scan cannot run, so the tool will not publish unscanned. The denylist is required even when the allow-list is empty. | Make the denylist resolvable (see Environment), then run again. |
| `denylist-match` | A selected file contains a denylist entry at the named line, or a selected file NAME contains one (the name is printed with the entry redacted). Binary files are scanned too. | Remove the string from the file, rename the file, or take it out of the allow-list, in a PR. Release again. |
| `git-crypt` | A selected file has `filter=git-crypt` or a named-key filter (`filter=git-crypt*`) at the released commit. Publishing it would send ciphertext. | Remove the path from the allow-list. |
| `symlink-escape` | A selected symlink is not a relative link to a selected regular file: it is absolute, leaves the repository, points at a directory, at another link, or at a path that is not selected. | Select the target file too, or remove the link from the allow-list. |
| `submodule` | A selected path is a submodule. | Remove it from the allow-list. |
| `no-allow-list` | The released commit has no `publish/<target>.allow`, or it is not a regular file. | Add the file in a PR and release again. |
| `bad-allow-line` | An allow-list line starts with `!`, `-`, `:` or `/`, holds a control character or a `.`, `..` or empty path component, is not a pattern git accepts, or the file holds a NUL byte. | Fix the line in a PR. |
| `stale-allow-line` | An allow-list line matches no file at the released commit, usually after a rename. | Fix or delete the line in a PR. |
| `unsafe-path` | A selected path holds a tab, a newline or another control character. | Rename the file or take it out of the allow-list. |
| `github-in-mirror` | The `tds-utils-public` selection contains a path under `.github/`. The mirror runs no workflows. | Remove the line. |
| `workflow-trigger` | A selected workflow under `.github/workflows/` in the `workflows` target has a trigger other than `workflow_call`, a form the recognizer cannot read, or is a symlink. Nothing may run in the target itself. | Remove the other trigger, or take the file out of the allow-list. |
| `not-released` | `<sha>` is not the head of `release`, or does not name a commit. | Use `git rev-parse release` in the source checkout, or release first. |
| `internal` | A check could not run (a tool it needs failed, or its result was short). The line reads `refused: internal: <check> -- the check could not run, so nothing can be cleared`. A check that cannot complete never counts as a pass. | Read the check name, find why the tool failed (git, awk, sort, tr, sed), fix it, and run again. |

## Push failures

A push can fail because the bot credential is missing or rejected, because
the network is down, or because the target repository does not exist. The
tool exits 1 and the target keeps its previous snapshot. Fix the cause and
run `tds-public <target> <sha>` again.

Until the owner creates `9atatimer/workflows` and
`9atatimer/tds-utils-public` (Issue#827), the post-release step fails on the
push. The release itself still stands; `tds-release` reports the step as
failed.

## What a publication looks like

- One commit per release on the target's default branch. The message is
  `release <sha>`, with the full sha of the released commit.
- The commit holds exactly the selected files, byte-identical to the
  released commit, and replaces the target's previous tree. A file removed
  from the allow-list disappears from the target's tree at the next release.
- If the selection is the same as the target's current tree, no commit is
  made and nothing is pushed.
- The push is never forced. The target's history only grows.

## What cannot be undone

A pushed snapshot is public for good. A later release can remove a file from
the target's tree, but not from its history or from anyone's clone. The
allow-list is the boundary, and the denylist is a second check on the
contents of allowed files. Run `-n` first.

## Environment

- `TDS_PUBLIC_SOURCE` -- the source repository to read, overriding the
  default (the repository that holds the script).
- `TDS_PUBLIC_REMOTE` -- the target's remote. For tests only: when it is
  set, the tool uses plain git and the ambient git identity and credentials.
  When it is unset, the remote is the target's GitHub HTTPS URL, and the
  clone, the commit and the push all run as 9atatimer-bot through
  `bin/asbot`. If asbot is missing or refuses, the run fails with exit 1;
  it never falls back to the owner's identity.
- `TDS_PUBLIC_ASBOT` -- the asbot to run, overriding the default (the one
  beside the script, then the one on `PATH`). The tests point it at a fake.
- `TDS_BLEED_DENYLIST` -- the denylist file.

The denylist resolves the same way `bin/bleed-guard` resolves it
(`docs/bleed-guard.md`, The denylist): `TDS_BLEED_DENYLIST`, then
`git config bleedguard.denylist`, then the default path in the private
checkout. The difference is the miss: `bleed-guard` skips silently without a
denylist, and `tds-public` refuses with `no-denylist`. `TDS_BLEED_GUARD=0`
and `bleedguard.enabled=false` do not turn this scan off. CI has no
denylist, so CI runs only the hermetic test suite and never a real
publication.

A first publication to a target with no commits creates the branch `main`,
with a first commit that has no parent.
