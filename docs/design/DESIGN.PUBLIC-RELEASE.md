# Public release: tds-utils goes private behind allow-listed mirrors

> **Date:** 2026-11-18
> **Authors:** 9atatimer-bot, for the owner
> **Tracking:** Issue#825

---

## Overview

tds-utils becomes a private repository. Its public face is two repositories
that receive only what a release selects and checks: `9atatimer/tds-utils-public`,
a mirror of the environment that runs no workflows, and `9atatimer/workflows`,
the reusable CI workflows and their tool code that other repositories call.
Both are written by a publish step in the release cycle. The step publishes
only allow-listed paths, scans every published file for private strings, and
refuses the whole publication on any doubt.

---

## Goals

- A path is published only if a reviewed allow-list for that target names it.
  A new file in tds-utils is private until an allow-list change says otherwise.
- A publication containing any denylist match, an encrypted file, or a
  structural violation for its target (below) is refused whole. Nothing is
  pushed, and the refusal names `file:line`, never the matched text.
- A publication with no denylist available is refused, not skipped.
- Each target receives one commit per release, carrying a snapshot of its
  allow-listed tree at the released commit. Neither target ever receives
  tds-utils history.
- A published file is byte-identical to the file at the released commit. The
  publish step selects and refuses; it never rewrites content.
- Every repository that calls `ocr-review.yml`, `review-settled.yml` or
  `adherence.yml` today, and `naatm-ci-magic`'s `bin/decide` fetch, works
  unchanged after tds-utils is private, by calling `9atatimer/workflows`.
- `9atatimer/tds-utils-public` has no `.github/` directory and runs no
  workflow.

---

## Non-Goals

- **Removing what is already public.** Clones, forks and caches of the
  current public history survive the switch to private. Scrubbing them is not
  this design.
- **Taking contributions on the mirrors.** Issues and PRs are turned off on
  both targets. All work happens in tds-utils.
- **Rewriting content to make it publishable.** A file that would need an
  edit to be safe stays private. Redaction is selection and refusal only.
- **Publishing tds-internal, or anything outside tds-utils.**
- **A public CI for the published code.** The code is tested in tds-utils
  before it is released. The targets carry no tests that run there.

---

## Architecture Overview

```
  tds-utils (private)                          public targets
  +-----------------------------+
  | master --(tds-release)--> release          +--------------------------+
  |                     |                      | 9atatimer/workflows      |
  |                     v                      |  one commit per release  |
  |   publish step (post-release)    push ---> |  .github/workflows/*     |
  |     |                                      |  (workflow_call only)    |
  |     +- read tree at released commit        |  bin/, lib/, adherence/  |
  |     +- select: target's allow-list         +--------------------------+
  |     +- refuse: denylist scan (required),
  |     |          encrypted files, symlinks   +--------------------------+
  |     |          out of the selection,       | 9atatimer/tds-utils-     |
  |     |          target structure rules      |   public                 |
  |     +- snapshot commit on target branch    |  one commit per release  |
  |                                  push ---> |  no .github/, Actions off|
  | publish/workflows.allow                    +--------------------------+
  | publish/tds-utils-public.allow
  +-----------------------------+

  callers (9atatimer/*, Nine-At-A-Time-Media/*)
    uses: 9atatimer/workflows/.github/workflows/ocr-review.yml@<sha>
    with: tools_ref: <same sha>      -> checkout 9atatimer/workflows@<sha>
```

---

## Design

### Allow-lists

| Item | Rule |
|---|---|
| Location | `publish/<target>.allow` in tds-utils, one per target |
| Format | One path or glob per line, relative to the repository root; `#` comments; no negation |
| Default | A path no line matches is not published |
| Review | An allow-list change is a PR like any other; the CODEOWNERS catch-all already requires the owner's approval |
| Stale lines | A line that matches no file at the released commit refuses the publication, so a rename cannot silently drop or move what is published |

The first `workflows.allow` is the code the three shared workflows check out
today, plus the workflows themselves:

```
.github/workflows/ocr-review.yml
.github/workflows/review-settled.yml
.github/workflows/adherence.yml
bin/ocr-review
lib/ocr-review/**
bin/review-settled
lib/review-settled.mjs
bin/adhere
bin/decide
lib/decide/**
adherence/**
```

The first `tds-utils-public.allow` is the owner's call (Open Questions).

### Paths are kept verbatim

A published file keeps its tds-utils path. The workflows' sparse checkouts
(`bin/ocr-review`, `lib/ocr-review`, `adherence`, ...) therefore stay valid
once each workflow's `repository:` names `9atatimer/workflows`. That edit is
made once, in tds-utils, as an ordinary change, not by the publish step.

### Refusals

The publish step refuses the whole publication, pushes nothing, and exits 1
when any of these hold. Each refusal names the rule and the path (and
`file:line` for a denylist hit).

| Rule | Applies to | Why |
|---|---|---|
| No denylist found | both | `bin/bleed-guard` skips silently without one; here that would publish unscanned |
| A selected file matches the denylist | both | The existing private-string check, run over every selected file in full, not over a diff |
| A selected file is git-crypt encrypted (`filter=git-crypt`) | both | `git archive` would publish ciphertext and the key's existence |
| A selected symlink's target is not also selected | both | It would publish a dangling link or reach outside the selection |
| A line of the allow-list matches nothing | both | See Allow-lists |
| Any selected path under `.github/` | tds-utils-public | The mirror runs no workflows |
| A selected workflow has any trigger other than `workflow_call` | workflows | Nothing may run in the target itself |
| The commit to publish is not the head of `release` | both | Only released history is published |

### Snapshot commit

- The step builds the selected tree in a temporary directory outside every
  checkout, from `git archive` of the released commit.
- It clones the target's default branch and replaces its tree with the
  snapshot. If nothing changed, it commits nothing and pushes nothing.
- Otherwise it makes one commit whose parent is the target's previous head,
  with the message `release <released sha>`, and pushes it. The push is
  never forced.
- The commit is made and pushed as `9atatimer-bot` over HTTPS.

### Where it runs

A step in `bin/tds-post-release`, so every release that the owner runs
publishes both targets. A refusal or a push failure is reported as a failed
post-release step: the release itself has already moved, and the targets
simply stay at their previous snapshot. `bin/tds-public` (the step's command)
also runs alone, with `-n` to report what would be published and every
refusal without pushing.

### Callers move to `9atatimer/workflows`

- `uses: 9atatimer/workflows/.github/workflows/<name>.yml@<sha>`, with
  `tools_ref` the same `<sha>`, a commit of `9atatimer/workflows`.
- The existing pin-bump tool moves every caller; tds-utils's own callers move
  too, so tds-utils runs the published copy like everyone else.
- Nine-At-A-Time-Media/template-tools `naatm-ci-magic` fetches `bin/decide`
  and `lib/decide` from `9atatimer/workflows` (its `decide-tools-ref` default
  becomes a workflows commit).
- The adherence skill's adoption docs (Skills, misvtt) name the new repository.

---

## Behaviors and Interfaces

The publish step is shell. Its use case is one flow function; the rules are
pure functions over a selection; the ports are the source tree, the
denylist and the target remote.

| Behavior | Use case (signature) | Ports | Given / When / Then |
|---|---|---|---|
| A release publishes its allow-listed tree | `publish_target <target> <released-sha>` -> Publication | source tree, denylist, target remote | Given a released commit and an allow-list naming `bin/a`, When the target is published, Then the target's new commit holds `bin/a` byte-identical and nothing else |
| An unlisted file is never published | (same) | (same) | Given `bin/b` that no line names, When published, Then the target has no `bin/b` |
| A denylist hit refuses everything | (same; error path) | (same) | Given a selected file containing a denylist entry, When published, Then nothing is pushed, the exit is 1, and the output names `file:line` and not the entry |
| No denylist refuses | (same; error path) | denylist | Given no denylist, When published, Then nothing is pushed and the refusal says so |
| A stale allow-list line refuses | (same; error path) | source tree | Given a line matching no file, When published, Then nothing is pushed and the line is named |
| A workflow with its own trigger refuses | (same; error path) | source tree | Given a selected workflow with `on: push`, When `workflows` is published, Then nothing is pushed |
| The mirror never receives `.github/` | (same; error path) | source tree | Given a `tds-utils-public` allow-list that selects `.github/x`, When published, Then nothing is pushed |
| Encrypted and escaping files refuse | (same; error path) | source tree | Given a selected git-crypt file, or a selected symlink to an unselected path, When published, Then nothing is pushed |
| An unchanged release adds no commit | (same) | target remote | Given a target whose head already holds the snapshot, When published, Then no commit is made |
| Only the released commit is published | (same; error path) | source tree | Given a sha that is not the head of `release`, When published, Then nothing is pushed |
| A dry run publishes nothing | `publish_target -n <target> <released-sha>` -> Report | source tree, denylist | Given any release, When run with `-n`, Then it prints the selection and every refusal and pushes nothing |

The tests use a scratch repository as the source tree, a fixture denylist,
and a local bare repository as the target remote.

---

## Data Model

| Term | Meaning |
|---|---|
| Target | A public repository the release writes: `workflows` or `tds-utils-public`, with its allow-list and its structure rules |
| Allow-list | `publish/<target>.allow`: the paths and globs that may be published to that target |
| Selection | The files at the released commit that the allow-list matches |
| Refusal | A rule that failed for a selection; any one refusal stops the publication |
| Snapshot | The selected tree, byte-identical to the released commit |
| Publication | One commit on the target holding a snapshot, message `release <sha>`, or no commit when the snapshot is unchanged |

---

## Security Considerations

- **The allow-list is the boundary.** The denylist is a second check for
  strings inside allowed files, not the boundary itself.
- **The denylist stays private.** It is read from tds-internal, as
  `bin/bleed-guard` reads it today, and is never published. Its absence
  refuses.
- **Refusal output never carries matched text**, so a refusal cannot leak
  into a terminal log or transcript.
- **Nothing runs on the targets.** The mirror has no `.github/` and Actions
  turned off. `workflows` keeps Actions on, because callers run its workflows,
  but every workflow in it is `workflow_call` only, so none runs in that
  repository's own context.
- **The bot pushes; nothing is forced.** A target's history only grows, so a
  bad publication is visible and is corrected by the next release.
- **Publication cannot be undone.** Once a snapshot is pushed, it is public;
  a later release can remove a file from the target but not from its history
  or from anyone's clone.

---

## Operability

- **Release class:** R2. It changes what the public can read and what every
  caller's CI runs.
- **Stages:** none. A dry run (`tds-public -n`) is the preview.
- **Failure modes:**
  - A refusal: read the named rule and path, fix the allow-list or the file
    in a PR, release again.
  - A push failure (bot token, network): the post-release step fails; run
    `tds-public` again after fixing the cause.
  - A caller breaks after a pin bump: the previous `workflows` commit is
    still there; pin back to it.
- **Rollout, in this order:**
  - The owner creates `9atatimer/workflows` and `9atatimer/tds-utils-public`,
    gives the bot push access, and turns off issues and PRs on both and
    Actions on the mirror.
  - The publish step and both allow-lists land; the first `workflows`
    publication goes out.
  - One Nine-At-A-Time-Media repository calls `ocr-review.yml` from
    `9atatimer/workflows` and runs a review, which proves cross-account calls
    work.
  - Every caller moves (pin bumps, template-tools `naatm-ci-magic`, the skill
    docs).
  - The first mirror publication goes out.
  - The owner makes tds-utils private.
  - tds-utils's own CI moves where it can to the niner pool, which serves
    only private repositories.
- **Rollback:** before tds-utils is private, every step reverts by pinning
  callers back to a tds-utils commit. After, the owner can make tds-utils
  public again; nothing in this design prevents that.
- **Cannot be rolled back:** anything a publication has pushed.

---

## Key Decisions

| Decision | Rationale | Authorized by |
|---|---|---|
| Allow-lists for both targets, never deny-lists | A new file must not be exposed by accident | Owner, 2026-11-18; Issue#825 |
| One `workflows` repository for reusable workflows, composite actions and their tool code | One SHA names a consistent set; a second repository doubles every caller's pins for no gain | Owner, 2026-11-18; Issue#825 |
| Both targets come from the same release-cycle publish step | One development loop and one gate; published code was tested in tds-utils | Owner, 2026-11-18; Issue#825 |
| Snapshots, never history | Old commits cannot leak what a later release removed | Issue#825 |
| Select and refuse; never rewrite | A rewritten file is a file nobody reviewed in that form | Issue#825 |
| Paths kept verbatim | The workflows' sparse checkouts keep working; the step has no path mapping to get wrong | Issue#825 |
| The mirror's first allow-list is `emacs/dot.emacs.d/**` alone, with no README or setup script | The owner needs only the emacs configuration on other machines; start small and add trees one at a time | Owner, 2026-11-20; Issue#833 |

---

## Open Questions

- **The first mirror allow-list.** Which top-level trees go public: for
  example `bin/`, `bash/`, `macos/`, `emacs/`, `git-config/`, `git-aliases/`,
  `git-hooks/`, `README.tds`? `docs/`, `tasks/`, `TODO_PLAN.md`, `AGENT.md`,
  `clai.d/` and `lmde/` describe the private setup in detail and are not
  obvious candidates. The owner decides, file by file where needed.
- **macOS CI cost once private.** The `smoketests`, `chores` and
  `dynomark-daemon` jobs run on `macos-latest`, which a private repository
  pays for at ten times the Linux rate. Keep, reduce, or move them?
- **`PUBLIC.REPO` and the pre-commit bleed guard.** Keep them on a private
  tds-utils, since its content still feeds two public targets? The publish
  step's scan is the gate either way.
- **The mirror's README and licence.** What it says about being a mirror,
  and which licence the published files carry.
- **Machines without access to the private repository.** A machine that
  only needs the environment would clone the mirror. Does `tds-install`
  need a mode for that?

---

## Rejections

| Alternative | Why not |
|---|---|
| Deny-list for the mirror | A new file is public until someone remembers to deny it |
| Separate `workflows` and `actions` repositories | Two pins per caller and two targets, for one set of code |
| Callers use `tds-utils-public` | The mirror would need `.github/workflows`, breaking "runs no workflows", and every pin would follow the mirror's selection |
| Keep the workflows in tds-utils and make only it public | That is the status quo the owner is leaving |
| Move the workflows into Nine-At-A-Time-Media/template-tools | Couples the 9atatimer fleet's CI to the org's repository and its release process |
| Publish history with secrets filtered out (`git filter-repo` per release) | Slow, and one missed rule leaks every past version; snapshots leak at most the current one |
| Rewrite private strings to placeholders at publish | Publishes files in a form nobody reviewed |
| Develop the workflows directly in `9atatimer/workflows` | Splits the code from its tests and its gate in tds-utils |

---

## Future Considerations

- A publish of tds-internal's public-safe parts, if one is ever wanted,
  would be a third target under the same rules.
- A check in tds-utils CI that runs `tds-public -n` on every PR, so a
  refusal is seen before release rather than after.

---

## Related Documents

- `docs/bleed-guard.md` -- the denylist check this design runs over whole files
- `docs/design/ENV-DISTRIBUTION.DESIGN.md` -- `tds-export`'s deny-list export, a different channel
- `docs/design/OCR-ON-DEMAND.DESIGN.md` -- the main caller-facing workflow
- `docs/design/DESIGN.ARCH-ADHERENCE.md` -- the adherence engine that `workflows` carries
