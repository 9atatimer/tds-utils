# orgmarks: the one-click sync exploration

> **Status:** groundwork, not a live plan. The approach described here was
> designed, reviewed, and shelved. The direction changed. This file exists
> so the findings outlive the approach.
>
> **Date:** 2026-07-31 -- 2026-08-23
> **Artifacts:** PR #185 (merged, `d9bb02f`), issue #189 (open, never run)
> **Design:** [BOOKMARK-ORGANIZER.DESIGN.md](../../design/BOOKMARK-ORGANIZER.DESIGN.md)

## What was asked

`orgmarks` had just landed (#165). It read a Chrome bookmark export,
reorganized it around task intent, and wrote a Netscape HTML file. Getting
that file back into Chrome was a manual chore: import, spot-check, delete
the old roots, drag the new tree up.

The ask was to close that loop. One command that downloads, organizes, and
uploads bookmarks to Chrome seamlessly -- a CLI, with a browser extension
accepted only if a CLI could not do it.

## What was done

**Answered the feasibility question: yes, a pure CLI, no extension.** The
read half already existed (`--from-profile` reads Chrome's `Bookmarks` JSON
directly). The write half needed a JSON sink and a way to guarantee Chrome
is not running while the profile is written.

**Designed `orgmarks sync`** and merged it as #185. Not implemented -- design
only. It added a Chrome lifecycle guard, a write protocol, an archive and
restore story, and a set of prerequisite changes to existing code.

**Ran five rounds of adversarial review** (codex on the PR). Fourteen
findings, all confirmed against the source, none rejected. The design at the
end of round five was substantially different from the one at the start.

**Cut issue #189**: the experiments that gate the whole approach. Never run.
The exploration stopped here.

## What is worth keeping

The design is approach-specific. These findings are not -- they apply to
anything that writes a Chrome profile, and several are defects in `orgmarks`
as it stands today.

### 1. The existing reader is lossy, and that is a live problem

`ChromeJsonSource` was built to feed a Netscape HTML emitter. HTML has no
GUIDs, no file-level envelope, and second-granularity timestamps, so
discarding all three was correct for that job. Any writer inverts the
requirement: **anything the reader drops is something a writer silently
rewrites.**

Four classes found by inspection, none fixed:

| Dropped | Where | Consequence for any writer |
|---|---|---|
| Folder and root GUIDs | `Folder` has no `guid` field; `_node_to_folder()` reads it only for bookmarks | A retained folder written back with a new GUID propagates as delete+create and takes its whole subtree with it |
| Top-level keys (`sync_metadata`, others) | `parse_chrome_json()` returns `BookmarkTree(roots=...)` and drops the rest | Nowhere for the value to live between load and emit; a writer must drop or fabricate it |
| Sub-second timestamps | `_chrome_date_to_epoch()` computes `micros // 1_000_000` | Every non-second-aligned bookmark gets a rewritten `date_added`, i.e. a metadata update for the whole collection |
| Node-local fields (`date_last_used`, `date_modified`, `meta_info`) | `Bookmark` and `Folder` have nowhere to put them | Silently rewritten on every node of every write |

The list was assembled by review, not by inspection of a real file. Assume
it is incomplete. Issue #189's E4 exists to replace it with a measured
inventory, and that step is worth doing under any approach.

### 2. GUIDs are identity; node IDs are not

Chrome Sync reconciles by GUID. A moved node that keeps its GUID propagates
as a *move*; one that loses it propagates as delete-plus-create, losing
per-device state. Node `id` values are reassigned freely by Chrome and carry
no identity.

Two consequences that are easy to get backwards:

- **A duplicated GUID is worse than a missing one.** Sync cannot reconcile
  two nodes claiming one identity, and the failure is non-local. This bites
  immediately in `orgmarks`, because the planner inserts the *same*
  `Bookmark` object into both its intent folder and the generated
  `Reference` subtree.
- **Regenerated nodes need *derived* GUIDs, not random ones.**
  `_classifiable()` rebuilds the Reference index every run. Minting a random
  GUID per copy makes the entire index delete+create on every run --
  fleet-wide churn proportional to collection size, and a direct violation
  of the repeatability goal. A UUIDv5 over (namespace, primary GUID,
  placement) is stable across runs with no matching pass.

### 3. Writing the profile is a mutual-exclusion problem, not a file-format problem

Chrome holds its bookmark tree in memory and rewrites `Bookmarks` on exit.
Writing under a running Chrome is not a race that can be won -- it is a
guaranteed silent clobber. Everything hard about the approach follows from
that, and the JSON emit itself is mechanical.

Wrong turns worth not repeating, each of which reads as the obvious answer:

- **Re-checking that Chrome is stopped just before writing.** That is a
  TOCTOU check, not exclusion. A browser launched between the check and the
  `rename()` still clobbers.
- **Reading the profile before quitting Chrome.** Chrome flushes on exit, so
  a bookmark added or synced during a slow classify stage lands on disk at
  quit time and is then overwritten by a plan built from the older snapshot.
  The fix is ordering (quit, claim, *then* load), not detection.
- **`SIGKILL` to honor a quit timeout.** Manufactures exactly the corrupted
  profile the guard exists to prevent.
- **Post-write verification as a backstop for a lock you do not trust.**
  Chrome can break the lock, load the old tree before the rename, pass
  verification, and overwrite from memory afterward. Verification detects
  one failure mode and cannot catch the general case.
- **One lock for two questions.** "Is Chrome running" and "may this tool
  touch the profile" have different owners and different staleness rules.
  Once the tool claims Chrome's `SingletonLock`, any rule permissive enough
  to break a stale Chrome lock lets a second instance of the tool break the
  first one's.
- **Staleness meaning "unfamiliar" rather than "dead."** Breaking a lock
  held by any live process is the same clobber, with a different culprit.

### 4. The unverified facts that gate everything

Three questions about Chrome's behavior were assumed, never measured, and no
amount of review answers them. They are specified as runnable experiments in
**issue #189**:

1. **Does Chrome refuse to start when `SingletonLock` is held by a live
   non-Chrome process?** This is the gate. If it breaks the lock instead,
   lock-based exclusion does not work and needs replacing.
2. **Is omitting the `checksum` key safe, and do GUIDs survive the
   rewrite?** The design bet on omit-rather-than-recompute, since node IDs
   are not identity.
3. **Does preserved `sync_metadata` survive a rewritten tree, or does Chrome
   re-merge from the server?** Requires a throwaway account; the design
   treated re-merge as recoverable.

Issue #189 remains valid under any approach that writes the profile. It is
also mostly wasted effort under an approach that does not.

### 5. The archive is the reason a destructive feature is allowed to exist

If a tool can rewrite the bookmark collection, the recovery story carries
the feature. What survived review:

- Immutable, UTC-stamped snapshot directories; nothing rewrites history.
- **Plain uncompressed `Bookmarks` files under their original name.**
  Recovery must not require the tool -- `cp` with the browser closed is a
  complete manual restore, and that has to hold on the day the tool is what
  broke. No tar, no bespoke container.
- sha256 per file, verified on write and again before any restore.
- **Keep everything.** Count-based retention fails the case the archive
  exists for: a few runs in one afternoon evict last week's good state, and
  the collection is kilobytes. Thin by age band if ever needed.
- Restore snapshots current state first, so restoring is itself undoable.
- Off-machine durability is a *location* choice (`ORGMARKS_ARCHIVE_DIR`
  pointed somewhere already backed up), not an uploader inside the tool.
  Every backend would be a new dependency and a new way for the whole
  collection to leak in plaintext.

### 6. On a signed-in profile, every write is a fleet action

Not a footnote. A reorganization propagates to every device on the account
the moment the browser restarts. That reframes several decisions -- it is
why GUID preservation is a contract rather than a nicety, why timestamp
truncation matters, and why "it only moved three bookmarks" is not a measure
of blast radius.

## Why it stopped

Not because a defect was found. Because the review did not converge:
severity across five rounds ran P1,P1,P1 -> P1,P1 -> P1,P1,P2 -> P2,P2,P2 ->
P1,P1,P2, and the last three rounds each *grew* the prerequisite work rather
than confirming it.

The structural reason: the approach writes a file format owned by another
program, whose behavior under the exact conditions that matter is
undocumented and unverified. Review can keep finding real defects in a design
like that indefinitely without ever making it shippable. The honest next step
was an experiment, not another revision -- hence #189, and hence the pause
that led to changing direction.

Worth recording plainly: the recurring failure in this exploration was
**narrowing a race and calling it fixed**. It happened twice at increasing
depth before the pattern was named, and once more as a self-contradiction
introduced by fixing one section without sweeping the others. The corrective
in every case was reordering so the window did not exist, never adding a
check.

## If the new direction still touches Chrome

- The lossy-reader findings (1) are defects today, independent of any sync
  feature. Worth fixing on their own merits if `orgmarks` keeps a Chrome JSON
  path.
- The GUID semantics (2) apply to anything that writes bookmarks, including
  an extension using `chrome.bookmarks` -- that API moves nodes by id and
  sidesteps the file entirely, which removes problems (3) and (4) wholesale
  while adding an install and permissions surface.
- The archive design (5) is approach-independent and is the piece most worth
  carrying forward verbatim.
- Issue #189 should be closed as not-planned if the new direction does not
  write the profile directly.
