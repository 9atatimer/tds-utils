# Bookmark Organizer (orgmarks)

> **Status:** APPROVED
> **Date:** 2026-07-23
> **Revised:** 2026-07-30 -- profile write-back (`orgmarks sync`) promoted
> from Future Considerations to Design; see Rejections for what changed.
> **Authors:** Todd + Claude
> **Depends on:** [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md)

---

## Overview

Chrome bookmarks accumulate faster than they get filed, and the folder tree
drifts away from how work actually happens. `orgmarks` is a local CLI that takes
a Chrome bookmark export, reorganizes it around task intent (work, fun,
self-education, writing) using deterministic rules first and an LLM second,
and emits a cleaned tree for re-import -- guided by a human-editable YAML
taxonomy file that the tool itself grows over time.

---

## Goals

1. **Round trip** -- Export from Chrome, run one command, import the result
   back; zero bookmarks lost and none duplicated within a folder. Two
   separate checks: **losslessness** (every input URL appears in
   output-minus-Reference; the generated Reference copies are the only
   additions) and **per-folder uniqueness** (no folder outside a pinned
   subtree contains the same URL twice; pins pass through verbatim,
   dupes and all).
2. **Intent-first organization** -- Every bookmark outside a pinned subtree
   lands in an intent-rooted folder (e.g. `work/dev`, `writing/reference`),
   or in a single `_triage` folder when confidence is below threshold.
   No bookmark remains "unfiled" outside `_triage`; pinned bookmarks stay
   exactly where the human put them.
3. **Hint-driven, not oracle-driven** -- A YAML taxonomy file seeds the
   structure; the tool must produce a usable tree from an empty hints file
   and a better one from a curated one.
4. **Repeatable with low churn** -- Running twice in a row on the same input
   produces an identical tree (rules are deterministic; LLM assignments are
   persisted as learned rules, so the second run needs no LLM calls).
5. **Restructure on demand** -- A `--restructure` mode lets the LLM propose a
   reworked folder tree (new interest areas, collapsed dead branches),
   presented as a reviewable plan before anything is written.
6. **Exhaustive reference index** -- A single generated `Reference` subtree
   files a copy of *every* bookmark into a categorical taxonomy
   (`technical/security/ddos/...`). Invariant: URL-set(Reference) equals
   URL-set(entire collection). The intent tree is for working (90% of
   lookups); the card catalog is for remembering (10%).
7. **Dry-run by default** -- `plan` mode prints the full move/create/merge
   report; `apply` mode is an explicit second step.

---

## Non-Goals

- **Not a bookmark manager.** No database, no tags, no search UI. Chrome
  remains the system of record; orgmarks is a batch groomer.
- **Not a browser extension.** No Chrome permissions, no store listing, no
  background process.
- **Not a sync service.** One machine's export in, one file out. Chrome Sync
  propagates the result.
- **Not a dead-link checker (v1).** Reachability crawling is deferred; it is
  slow, network-bound, and orthogonal to organization.
- **Not multi-browser (v1).** Netscape HTML is a de facto standard so
  Firefox/Safari exports may happen to work, but only Chrome is supported.

---

## Architecture Overview

```
chrome://bookmarks Export                         taxonomy.yml
        |                                        (hints + learned rules)
        v                                             |     ^
+----------------+    +------------+    +-------------+     | learned
| Loader         |    | Normalizer |    | Rule Engine |     | rules
| (Netscape HTML |--->| (dedupe,   |--->| (domain/    |     | written
|  or Chrome     |    |  URL strip)|    |  path match)|     | back
|  Bookmarks     |    +------------+    +------+------+     |
|  JSON)         |                             |            |
+----------------+                     unmatched residue    |
                                               v            |
                                        +-------------+     |
                                        | LLM         |-----+
                                        | Classifier  |
                                        | (port)      |
                                        +------+------+
                                               |
                                               v
                                        +-------------+    +--------------+
                                        | Planner     |--->| Emitter      |
                                        | (tree build,|    | (Netscape    |
                                        |  churn min, |    |  HTML out +  |
                                        |  triage)    |    |  plan report)|
                                        +-------------+    +--------------+
```

Core (Normalizer, Rule Engine, Planner) is pure logic on an in-memory
bookmark tree. Volatile mechanisms sit behind ports at the edges:

| Axis of change | Seam |
|---|---|
| Bookmark wire format (Netscape HTML vs Chrome JSON) | `BookmarkSource` / `BookmarkSink` ports |
| LLM vendor/model (claude-cli, OpenAI-compat, Ollama) | `Classifier` port; provider + model id in `taxonomy.yml`, never in code |
| Taxonomy content (intents, rules, thresholds) | `taxonomy.yml`, parsed once into a `Taxonomy` value object |
| Browser process control (macOS `osascript` vs Linux signals) | `BrowserLifecycle` port; the guard sequence is pure logic over its three verbs |

No single-implementation-forever ports: each of these already has two real
implementations or a vendor boundary.

---

## Design

### Loader (BookmarkSource port)

| Responsibility | Details |
|---|---|
| Parse Netscape HTML export | The `chrome://bookmarks` Export format: nested `<DL><DT>` with `ADD_DATE`, folder names. Primary input. |
| Parse Chrome `Bookmarks` JSON | The live profile file (`~/Library/Application Support/Google/Chrome/<Profile>/Bookmarks` on macOS). Read-only convenience input (`--from-profile`) that skips the manual export step. Preserves GUIDs and dateAdded. |
| Produce a `BookmarkTree` | Roots preserved as-is: `bookmarks_bar`, `other`, `synced`. |

### Normalizer

| Responsibility | Details |
|---|---|
| Dedupe (per-folder scope) | Exact-URL duplicates *within one folder* collapse to one node; the survivor keeps the oldest `add_date` and the "best" title (longest non-URL-shaped). The same URL in different folders is a deliberate breadcrumb -- preserved, listed in the report as info only. |
| URL canonicalization (compare-only) | Strip `utm_*`/`fbclid`-class tracking params and trailing slashes *for comparison*; the stored URL is never rewritten. |
| Empty-folder pruning | Folders left empty after moves are dropped (reported). |

### Taxonomy file (`taxonomy.yml`)

Human-owned hints plus machine-appended learned rules, one file, checked into
whatever repo the user keeps it in (it contains URLs -- private repo, not
tds-utils).

```yaml
version: 1
intents:                      # top-level folders, in display order
  - name: work
    hint: "employment, clients, 9atatime, infra"
  - name: fun
  - name: self-education
    hint: "courses, papers, tutorials I am working through"
  - name: writing
pins:                         # subtrees orgmarks must not touch
  - path: "bookmarks_bar/Daily"
rules:                        # deterministic, first match wins
  - match: { domain: "github.com", url_prefix: "/9atatimer" }
    folder: "work/dev"        # intent home
    ref: "technical/dev/github"   # reference-index category (optional)
    source: human
  - match: { domain: "news.ycombinator.com" }
    folder: "fun/hn"
    ref: "culture/tech-news"
    source: learned           # appended by orgmarks from an LLM assignment
reference:
  root: "other/Reference"     # where the generated card catalog lives
  seeds:                      # optional top-of-taxonomy hints
    - technical
    - culture
    - finance
llm:
  provider: claude-cli        # or openai-compat endpoint name, or ollama
  confidence_threshold: 0.7   # below this -> _triage
shape:
  max_umbrella_links: 3       # direct links allowed atop a hub folder
triage_folder: "_triage"
```

| Field | Contract |
|---|---|
| `intents` | Ordered; these become the top-level folders of the organized tree, which roots at `Bookmarks Bar` (revised default -- confirmation tracked in Open Questions #2). `hint` text is passed verbatim to the LLM. |
| `pins` | Subtrees copied through untouched; their bookmarks are excluded from classification and dedupe-moves. |
| `rules` | Evaluated top-to-bottom, first match wins. `match` supports `domain`, `url_prefix` (path prefix), `title_regex`. Human rules sort before learned rules. |
| `llm` | Provider selection and threshold. Absent block = rules-only run (LLM stage skipped, residue goes to `_triage`). |

Parsing/validation via Pydantic at this boundary; the core sees only a frozen
`Taxonomy` dataclass.

### Rule Engine

Pure function: `(Bookmark, Taxonomy) -> FolderPath | None`. Applies pins,
then rules. Everything unmatched is the residue handed to the classifier.
Bookmarks already sitting in a folder that maps to a valid intent path are
treated as an implicit rule (stay put) unless `--restructure` is set --
this is the churn minimizer.

### LLM Classifier (Classifier port)

| Responsibility | Details |
|---|---|
| Classify residue | Batches of <= 50 bookmarks (title, URL, current folder path) plus the intents/hints and the current folder skeleton. Returns per-bookmark: `folder` (intent home), `ref` (reference category), `confidence`, optional `proposed_new_folder`. |
| Emergent-area detection | When residue bookmarks cluster on a concept with no intent home, the batch response's `proposed_new_folder` entries are aggregated by the Planner and surfaced in the report as "new area: <name>, N bookmarks". A new *subfolder* under an existing intent is created on `apply`; a new *top-level* intent is only ever proposed -- adding it to `intents` in taxonomy.yml is a human edit. |
| Restructure proposal (`--restructure`) | Sends the full folder skeleton with per-folder counts (not every bookmark) and asks for a revised skeleton: renames, merges, splits, new intent areas. Output is a plan, never applied without `apply`. |
| Learn-back | Every assignment at or above `confidence_threshold` is generalized (by domain, or domain+path prefix when the domain is split across folders) and appended to `rules` with `source: learned`. Next run, the rule engine handles it and the LLM is not called. |

Providers per the tech radar Trial ring: `claude-cli` (default -- rides the
Max plan, no metered key), any OpenAI-compatible endpoint, or local Ollama
for privacy-sensitive runs. Model id and endpoint live in `taxonomy.yml`.
Structured output enforced by JSON schema; a malformed batch response is
retried once, then that batch falls to `_triage` (never crash the run).

### Planner

Builds the output tree: pinned subtrees verbatim, then intent folders in
declared order, `_triage` last. Produces a `Plan` -- the list of moves,
folder creates/renames/deletes, dedupe collapses, and learned-rule appends --
which is both the dry-run report and the apply worklist.

#### Tree shape invariants (skinny tree)

Enforced mechanically by the Planner on every emit -- the LLM proposes
*where* a bookmark belongs, never the shape:

| Invariant | Rule |
|---|---|
| Hub or leaf | Every folder is a **hub** (subfolders present) or a **leaf** (links only). No third kind. |
| Umbrella links | A hub may hold at most `max_umbrella_links` (default 3) direct links, and only root-of-concept URLs (path depth <= 1, domain matching the folder's concept -- e.g. `github.com` atop the GitHub hub). |
| Big-buttons first | Within a hub: umbrella links first, then subfolders. **Nothing after the folders.** Chrome round-trips manual order, so this survives import. |
| Singleton wrapping | A non-umbrella link stranded in a hub is wrapped into its own single-element subfolder rather than left dangling. Single-link leaves are valid by design. |

#### Reference index (the card catalog)

A generated subtree at `reference.root` holding a copy of every bookmark,
organized by concept (`technical/security/ddos/...`), not by task. Its
properties differ from the intent tree on purpose:

| Property | Intent tree | Reference index |
|---|---|---|
| Navigated by | muscle memory (90% of lookups) | browsing/recall (10%) |
| Churn policy | minimize; moves only when confident | none -- rebuilt from scratch every run |
| Coverage | every bookmark has one home (or `_triage`) | exhaustive: every bookmark, including pinned and triaged ones |
| Depth | skinny (hub/leaf invariants) | deeper taxonomy allowed; same hub/leaf ordering rules |
| Authority | human-owned, tool-maintained: orgmarks files, prunes, and proposes new areas; top-level intents change only by human edit | tool-owned entirely: a deliberately systematic, stable taxonomy (card-catalog boring beats clever) |

Rebuild is deterministic: `ref` categories come from rules (human and
learned) exactly like intent homes; the LLM assigns a `ref` category only
for bookmarks no rule covers, and high-confidence assignments are learned
back into the same rule entry. Because the index is derived, a bad rebuild
costs nothing -- rerun and it regenerates.

### Emitter (BookmarkSink port)

| Responsibility | Details |
|---|---|
| Netscape HTML out | `bookmarks-organized-<date>.html`, importable via `chrome://bookmarks` Import. The `apply` write path. |
| Chrome JSON out | `ChromeJsonSink`, the mirror of the existing `ChromeJsonSource`: GUIDs and `date_added` round-trip at full precision, `checksum` omitted, `sync_metadata` and unrecognized top-level keys passed through. Requires the prerequisite work below -- today's source is lossy on all three counts. The `sync` write path. |
| Plan report | Human-readable summary to stdout: N moved, N deduped, N triaged, folders created/removed, learned rules added. |
| Taxonomy write-back | Appends learned rules to `taxonomy.yml`, preserving comments and key order (ruamel-style round-trip parse); on `apply` and `sync`, never on `plan`. The learned-rule ratchet is a property of any writing mode -- without it `sync` would re-classify the same residue every run. |

Import caveat for the HTML path (documented in `--help` and the report):
Chrome imports into an `Imported` folder; the manual step is import,
spot-check, delete the old roots, drag the new tree up. `orgmarks sync`
below removes that step entirely; `apply` keeps the HTML path for
non-Chrome targets and for anyone who wants a file to eyeball first.

### Profile write-back (`orgmarks sync`)

The one-command path: read the live profile, plan, write the profile back.
`--from-profile` already reads Chrome's `Bookmarks` JSON preserving `guid`
and `date_added`, so this adds a `ChromeJsonSink` plus a lifecycle guard.
The guard is the whole design; the JSON emit is mechanical.

#### Chrome lifecycle guard

Chrome holds its bookmark tree in memory and rewrites `Bookmarks` on exit.
Writing the file under a running Chrome is not a race we can win -- it is a
guaranteed silent clobber. So the guard is a precondition, not a mitigation.

| Step | Action | On failure |
|---|---|---|
| DETECT | Read `<user-data-dir>/SingletonLock`; it is a symlink whose target is `<hostname>-<pid>`. Chrome is running iff that pid is alive and its executable is Chrome. | Unreadable/absent lock -> treat as not running. Lock present but pid dead or foreign -> stale, log and treat as not running. |
| PROMPT | Chrome running: print the profile path and ask for confirmation to quit it. `--yes` skips the prompt; `--no-quit` refuses instead of asking. | Declined -> exit 3, nothing written. |
| QUIT | macOS `osascript -e 'quit app "Google Chrome"'`; Linux `SIGTERM` to the lock's pid. Then poll for the lock to clear, 30s default (`--quit-timeout`). | Still held at timeout -> exit 4, nothing written. **Never escalate to `SIGKILL`** -- a killed Chrome is exactly the half-written profile this guard exists to prevent. |
| CLAIM | Take `SingletonLock` ourselves (symlink to `<hostname>-<our-pid>`) so a relaunched Chrome cannot attach to the profile. Claimed **before** LOAD and held across the whole pipeline; released after the post-rename verification, in a `finally` and a signal handler. | Cannot claim -> exit 4, nothing written. |
| WRITE | Re-`readlink()` the lock and confirm we still own it, then the backup + emit protocol below, then verify the rename landed. | Ownership lost -> exit 4, nothing written. Any other failure -> restore from backup, release the lock, then continue to RESTART. |
| RESTART | Only if we quit it **and** `--no-restart` was not passed: relaunch (`open -a "Google Chrome"` / the resolved Linux binary), detached, and do not wait on it. Both conditions apply on every exit path, success and failure alike. | Relaunch failure is reported, not fatal -- the profile is already consistent. |

`SingletonLock` is per-user-data-dir, which is the correct granularity: the
file being written is shared by every profile under that directory. `pgrep`
is not a substitute -- it cannot distinguish a Chrome running against a
different data dir, and it sees nothing when the lock is merely stale.

Properties the sequence must hold:

- **Quit and claim *before* LOAD, not before EMIT.** The snapshot the plan
  is built from must be taken from a quiesced profile that orgmarks already
  holds the lock on. Reading first and quitting later is unsound: Chrome
  flushes its in-memory tree on exit, so any bookmark added locally or
  arriving via sync during the classify stage lands on disk at QUIT and is
  then overwritten by an output tree built from the older snapshot. That is
  silent data loss, propagated fleet-wide. Ordering the guard first removes
  the window rather than narrowing it.
- **Hold the lock; do not merely re-check it.** Re-reading `SingletonLock`
  before WRITE is a TOCTOU check, not mutual exclusion: a Chrome launched
  between the check and the `rename()` loads the old tree and overwrites it
  on exit. Instead, once Chrome has exited, orgmarks **claims**
  `SingletonLock` itself, symlinking it to `<hostname>-<our-pid>`, and
  holds it across load, plan, emit, and rename. That is Chrome's own
  mutual-exclusion primitive used for its intended purpose rather than
  raced against. Release happens after the rename, before RESTART, and in
  a signal handler and `finally` so a killed orgmarks does not leave the
  profile permanently locked.
- **Ownership loss is fatal.** Re-`readlink()` the lock immediately before
  the rename and confirm it still names our pid. If it does not, abort
  without writing (exit 4). Losing the lock means another Chrome is live on
  the profile, and *nothing* we write afterward is safe.
- **Revalidate the snapshot as a cheap assertion.** With the guard ordered
  first this should never fire, so treat a mismatch between the loaded
  snapshot and the on-disk file at write time as a bug, not a routine
  branch: abort, keep the backup, report.
- **Restart is a relaunch, not a session restore.** Tabs return only if
  Chrome is configured to continue where it left off. Stated in `--help`;
  not something orgmarks tries to fix.

The cost of quitting first is real and worth stating: Chrome is down for
the whole run -- including a classify stage that can take minutes on a
large residue -- not just for the write. That is the price of correctness
by construction, and for a batch groomer run occasionally it is the right
trade. `plan` still runs against a live Chrome, so the "what would it do"
question never requires closing the browser.

#### The lock experiment gates this design

Chrome's behavior when it finds `SingletonLock` held by a **non-Chrome**
process is unverified: it may refuse with "profile is in use," or it may
judge the lock stale and break it. This is not an implementation detail to
settle later -- **it gates the design**.

If Chrome breaks orgmarks-held locks, the mechanism above does not provide
exclusion and must be replaced, not patched. In particular, post-rename
verification is *not* a sufficient fallback, and the previous revision of
this document was wrong to imply it was: Chrome can break the lock and
load the old tree *before* our rename, verification then reads our own
fresh file and passes, and the still-running Chrome overwrites it from
memory minutes later. Verification catches a clobber that has already
happened by write time; it cannot catch one still queued in another
process's memory. It stays in the design as a cheap detector of one
failure mode, with no claim to catching the general case.

Test on a copied user-data-dir, before implementation, alongside
`checksum` and `sync_metadata`. A "Chrome breaks it" result sends this
section back to the drawing board.

#### Write protocol

1. **Back up** `Bookmarks` and `Bookmarks.bak` to
   `${XDG_STATE_HOME:-~/.local/state}/orgmarks/backups/<profile>/<utc-ts>/`.
   Outside the user-data-dir on purpose -- Chrome should never see our
   files. Retain the last N (default 10).
2. **Emit** the new JSON to a temp file in the profile directory, fsync
   the file, atomic `rename()` over `Bookmarks`, then **fsync the
   containing directory**. A torn write is not representable, and the
   directory fsync is what makes the rename itself durable: without it a
   power loss after `rename()` returns can leave `Bookmarks` reverted or
   missing, while orgmarks has already reported success and restarted
   Chrome. Do it before verification, release, and restart.
3. **Leave Chrome's own `Bookmarks.bak` alone.** It holds the pre-run tree
   and Chrome falls back to it if `Bookmarks` fails to parse -- a free
   second safety net. Chrome regenerates it on next exit.
4. **`orgmarks restore --profile NAME [--at TS]`** puts a backup back,
   under the same lifecycle guard. Same code path, reversed.

#### Two Chrome-internal fields

These are the parts of the file that are not ours, and both are
version-sensitive enough that the implementation must verify them against
the installed Chrome on a *copied* user-data-dir before this ships.

- **`checksum`** -- an MD5 over the tree that Chrome uses to notice external
  edits. Decision: omit the key rather than recompute it. A missing or
  mismatched checksum makes Chrome reassign node IDs, and node IDs are not
  identity in Chrome -- GUIDs are. Recomputing it means tracking an internal
  algorithm across Chrome releases for no durable benefit.
- **`sync_metadata`** -- bookmark sync state, stored in the same file on
  current Chrome. Decision: preserve the input file's value verbatim. If
  Chrome rejects it as inconsistent with the rewritten tree, it re-merges
  against the sync server, which is recoverable. Fabricating or dropping it
  is not obviously safer, and preserving it is the cheaper default.
  Preserving it requires an envelope that today's source does not have --
  see the prerequisite section below.

#### GUID preservation is mandatory

On the HTML path GUIDs are advisory. On the profile path they are the
contract: sync reconciles by GUID, so a moved node that keeps its GUID
propagates as a *move*, and one that loses it propagates as a delete plus a
create. The second form loses per-device state and is far more alarming
across a fleet.

The rule has two halves, and both matter:

- **Exactly one node carries an input GUID.** Any node the planner carries
  through from the input retains its GUID.
- **Every generated node gets a fresh GUID.** A GUID appearing twice in one
  tree is worse than a missing one -- sync cannot reconcile two nodes
  claiming the same identity, and the failure is non-local.

The second half is not hypothetical. The reference index inserts *the same*
`Bookmark` into both its intent folder and the generated `Reference`
subtree (`domain/planner.py`, reference-index loop). On the HTML path that
duplication is harmless; on the profile path it emits two nodes with one
identity. **The primary intent placement keeps the input GUID; each
reference-index copy is cloned with a fresh one.** Same for the pinned
verbatim copies, which duplicate by the same mechanism.

#### Prerequisite: carry what the sink must round-trip

**The existing source is lossy by design, and every loss is a defect on the
profile path.** `ChromeJsonSource` was built to feed a Netscape HTML
emitter, a format that has no GUIDs, no envelope, and second-granularity
timestamps -- so discarding all three was correct. A sink that writes the
profile back inverts that requirement completely: anything the source drops
is something `sync` silently rewrites, and on a signed-in profile every
silent rewrite propagates to the fleet.

Three separate instances of this have surfaced so far -- folder GUIDs,
top-level keys like `sync_metadata`, and sub-second timestamp precision --
which is enough to treat it as one systemic gap rather than three bugs.
Read the table below as "make the Chrome JSON path lossless," and assume
anything not yet audited is lossy until checked.

The worst of the three is folder identity: `_node_to_folder()` reads `guid`
for bookmarks only and the `Folder` model has no `guid` field at all, so a
retained folder written back with a fresh GUID propagates as delete+create
and takes its entire subtree with it. A wrongly-recreated folder is a much
larger blast radius than a wrongly-recreated bookmark.

So `sync` is not "add a sink plus a guard." It requires, first:

| Component | Change |
|---|---|
| `domain/model.py` | `Folder` gains `guid: str \| None = None`, matching `Bookmark`. A `ChromeProfileEnvelope` (or equivalent) wraps `BookmarkTree` with the opaque top-level fields the sink must return unaltered. |
| `adapters/chrome_json.py` | `_node_to_folder()` reads `guid` from folder nodes and the three root nodes. `parse_chrome_json()` stops discarding everything outside `roots` and returns the envelope. `_chrome_date_to_epoch()` stops truncating to whole seconds. |
| Timestamps | `_chrome_date_to_epoch()` computes `micros // 1_000_000`, so every sub-second remainder is gone by the time the domain sees it and no sink can reconstruct it. Retain the raw Chrome microsecond value (or store microseconds throughout) so `date_added` survives the round trip. |
| `domain/planner.py` | Carry folder GUIDs through rebuild; mint fresh ones for folders the taxonomy creates; clone reference-index and pinned copies with fresh GUIDs. |
| `adapters/netscape.py` | Unaffected -- Netscape HTML has neither GUIDs nor an envelope; the HTML path keeps today's behavior. |

The envelope is the non-obvious half. `parse_chrome_json()` today reduces
the whole file to `BookmarkTree(roots=...)` and drops every other top-level
key on the floor -- which is correct for a read-only source feeding an HTML
emitter, and fatal for a sink that promised to pass `sync_metadata` through
verbatim. There is nowhere for that value to live between load and emit, so
an implementer following the source-plus-sink description would have to
drop or fabricate it, triggering exactly the fleet-wide server re-merge the
decision above exists to avoid.

Treat unrecognized top-level keys the same way: carry them opaquely rather
than enumerating a fixed set. Chrome adds fields across releases, and a
sink that silently drops the ones it does not know about is a slow leak of
profile state.

The domain must not learn what `sync_metadata` means. It is an opaque blob
that rides from source to sink; only the adapters touch it.

Chrome's three root nodes have fixed, well-known GUIDs. Preserve them from
the input rather than minting or hardcoding them.

This is the real blast radius of `sync`, and it deserves saying plainly:
on a signed-in profile, the reorg reaches every device on restart. The
plan report says so before the write, and `sync` requires either an
interactive confirmation or `--yes`.

### CLI

```
orgmarks plan    [--input FILE | --from-profile [NAME]] [--taxonomy FILE] [--restructure]
orgmarks apply   [same flags] [--output-dir DIR]
orgmarks sync    [--profile NAME] [--taxonomy FILE] [--restructure]
                 [--yes] [--no-quit] [--quit-timeout SECS] [--no-restart]
orgmarks restore [--profile NAME] [--at TS] [--list]

plan:    read-only everywhere; prints the Plan.
apply:   writes the output HTML and appends learned rules to taxonomy.yml.
sync:    profile in, profile out, under the Chrome lifecycle guard. Implies
         --from-profile. Order is load-bearing (see the state machine):
         confirm-to-quit, quit Chrome, claim the lock, THEN load / plan /
         classify, print the Plan and the blast radius, confirm the write,
         emit, release, restart. Appends learned rules.
         Chrome is down from the first confirmation to the restart.
restore: put a backup back, under the same guard. --list shows what is kept.

Errors:
  input unparseable        -> exit 2, no output written
  taxonomy invalid         -> exit 2, Pydantic error listing
  LLM provider unreachable -> warn, degrade to rules-only, residue to _triage, exit 0
  quit declined            -> exit 3, profile untouched          (sync/restore)
  no exclusive lock        -> exit 4, profile untouched          (sync/restore)
      (Chrome would not exit, lock unclaimable, or ownership lost mid-run)
  profile write failed     -> exit 5, backup restored, Chrome restarted
```

`sync` is the one-command path; `plan` remains the way to see what it would
do without a lifecycle guard anywhere near the profile.

---

## State Machine

Pipeline stages per run (no persistent state between runs beyond
`taxonomy.yml`):

```
+------+   +-----------+   +-------+   +----------+   +------+   +------+
| LOAD |-->| NORMALIZE |-->| RULES |-->| CLASSIFY |-->| PLAN |-->| EMIT |
+------+   +-----------+   +-------+   +----------+   +------+   +------+
                                          (skipped if no llm block
                                           or provider unreachable)
```

| From | To | Trigger | Condition |
|---|---|---|---|
| LOAD | NORMALIZE | parse success | input readable and well-formed |
| NORMALIZE | RULES | always | -- |
| RULES | CLASSIFY | residue non-empty | `llm` block present and reachable |
| RULES | PLAN | residue empty, or LLM unavailable | residue -> `_triage` when skipping |
| CLASSIFY | PLAN | all batches resolved | failed batches -> `_triage` |
| PLAN | EMIT | mode == apply or sync | `plan` mode stops here and prints |

`sync` wraps the same pipeline in the lifecycle guard, with the entire
pipeline inside the lock. DETECT, PROMPT, QUIT and CLAIM all run **before**
LOAD, so the snapshot comes from a quiesced profile orgmarks already owns;
RESTART runs after EMIT on every exit path that quit Chrome, including the
failure ones.

```
   [DETECT/PROMPT/QUIT/CLAIM] --> LOAD ... PLAN --> EMIT --> [VERIFY,
              |                     |                |        RELEASE,
              |                     |                |        RESTART]
              +-- abort ------------+----------------+------------^
```

Ordering the guard ahead of LOAD costs a longer Chrome downtime and buys
the elimination of a whole bug class: there is no window in which Chrome
can accept a bookmark that the plan does not know about. `plan` is
unchanged and never touches the guard.

---

## Data Model

No database. In-memory frozen dataclasses:

```
Bookmark
+-- url            str (never rewritten)
+-- title          str
+-- add_date       int (epoch)
+-- guid           str | None   (present only from Chrome JSON input)
+-- source_path    FolderPath   (where it was)

BookmarkTree
+-- roots          dict[RootName, Folder]   # bookmarks_bar, other, synced

Assignment
+-- bookmark       Bookmark
+-- folder         FolderPath   # intent home
+-- ref            FolderPath   # reference-index category (always set)
+-- confidence     float        # 1.0 for rule hits
+-- via            "pin" | "rule" | "stay" | "llm" | "triage"

Plan
+-- moves          list[Assignment]
+-- dedupes        list[(kept: Bookmark, dropped: list[Bookmark])]
+-- folder_ops     list[Create | Rename | Delete]
+-- learned_rules  list[Rule]
```

---

## Security Considerations

- **Bookmark URLs are sensitive.** Titles+URLs go to the configured LLM
  provider. Default `claude-cli` keeps it on the Anthropic account already
  trusted with this data; the Ollama provider exists for anything that must
  stay local. The plan report never truncates -- what was sent is auditable.
- **`taxonomy.yml` leaks interests and repo names.** It must live in a
  private repo (tds-internal), never in tds-utils. orgmarks's code and
  this doc stay URL-free.
- **No secrets in the tool.** Provider credentials come from the provider's
  own config (claude-cli auth, env var for endpoints); never stored in
  `taxonomy.yml`.
- **Profile writes are opt-in and reversible.** `plan`, `apply`, and
  `--from-profile` open Chrome's `Bookmarks` read-only and never write the
  profile directory. Only `sync` and `restore` write, only under the
  lifecycle guard, only after a confirmation or `--yes`, and only with a
  backup already on disk.
- **`sync` on a signed-in profile is a fleet-wide action.** The reorg
  reaches every device on the account. The confirmation prompt says so
  explicitly rather than burying it in `--help`.
- **Backups contain the full bookmark collection.** They inherit the same
  sensitivity as `taxonomy.yml`: written 0600 under `XDG_STATE_HOME`, never
  into a repo, never into the user-data-dir.

---

## Off-the-Shelf Survey

| Candidate | What it is | Why it does not fit |
|---|---|---|
| **buku** | Mature CLI bookmark DB with Netscape import/export | Replaces Chrome as system of record; organizing back *into* Chrome's tree is not its model. |
| **Linkwarden / linkding / Raindrop.io / Pinboard** | Self-hosted or SaaS bookmark managers, some with AI tagging | Same category error: they want to *be* the bookmark home. The requirement is Chrome-in, Chrome-out. |
| **AI-organizer Chrome extensions** (Sprucemarks, "Bookmark Organizer AI", etc.) | In-browser sorters, some LLM-backed | Opaque prompts, no hint file, no dry-run diff, broad extension permissions, no repeatability guarantees; several are sort-by-attribute only, not semantic. |
| **Dead-link checkers** (bookmarks-organizer web tools) | Find 404s in an export | Orthogonal problem; explicitly deferred. |
| **One-off GitHub scripts** (LLM-sorts-your-bookmarks gists) | Single-shot GPT reorganizers | Prove the concept but: no taxonomy hints, no learned-rule ratchet, no idempotency, no churn control. Worth mining for Netscape-format parsing edge cases only. |

Conclusion: the *pieces* exist off the shelf (Netscape parsing, LLM calls);
the *behavior* -- hint-guided, repeatable, low-churn, round-trip grooming --
does not. Build small, reuse formats.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| System of record | Chrome itself; orgmarks is a batch filter | User workflow is export -> groom -> import; anything that owns the data adds a migration and a second UI. |
| Interchange format | Netscape HTML in and out; Chrome JSON read-only in | HTML is the only format Chrome will import; JSON read skips the export step when convenient. |
| Organizing principle | Intent-first tree (`intent/topic`), from `intents` in taxonomy.yml | User is task-oriented: "work with site X under intent Y"; site-first trees rot because intent is the retrieval key. |
| Classification order | Deterministic rules first, LLM only for residue | Cheap, fast, repeatable; LLM cost/latency scales with the *new* bookmarks, not the collection. |
| LLM learning loop | High-confidence LLM assignments appended to taxonomy.yml as `source: learned` rules | Each run makes the next one more deterministic; the LLM converges toward handling only genuinely novel material. |
| Churn control | In-place bookmarks with valid intent paths stay put unless `--restructure` | Muscle memory is part of the UX; full re-shuffles are opt-in. |
| Tree shape | Hub/leaf invariant (umbrella links, then folders, nothing after) enforced by the Planner | Shape is mechanical, so it must be deterministic code, not LLM judgment; skinny hubs are the user's stated navigation model. |
| Duplicate policy | Per-folder dedupe only; cross-folder copies preserved | The same URL under two folders is a deliberate thought-breadcrumb (28 of 29 dup copies in the reference export are cross-folder); it is also the mechanism that lets every bookmark appear in both its intent home and the reference index. |
| Task/reference duality | Intent tree primary + one generated exhaustive `Reference` subtree | No mode declaration at filing or hunting time: the pile stays the pile; when in recall mode, the card catalog is one known place and guaranteed complete. Derived data, so it is rebuilt fearlessly each run. |
| LLM vendor seam | `Classifier` port; provider/model in taxonomy.yml | Radar Trial ring has three viable providers today; vendor names stay out of the core. |
| Language / stack | Python 3.11+, uv, Click, Pydantic, pytest, mypy strict | Radar Adopt ring across the board; tree manipulation and YAML round-tripping are Python-comfortable. |
| Location | `bookmark-organizer/` top-level dir in tds-utils, launcher shim in `bin/orgmarks` | Follows the log-hoarder precedent for multi-file tools; bin/ stays the entry-point surface. |
| Safety model | `plan` (default, read-only) vs `apply`; URL-set equality check before emitting | A grooming tool that can silently drop bookmarks is worse than no tool. |

---

## Open Questions

1. **Intent list** -- work / fun / self-education / writing came from the
   prompt; is that the real top level, and is `work` one bucket or split by
   employer/project?
2. **Bookmarks bar policy** -- The reference export roots the *entire*
   organized tree under `Bookmarks Bar` (Other bookmarks holds only loose
   strays), so "pin the whole bar" would exempt everything. Revised default:
   the bar is the organized tree; `pins` name specific bar subfolders to
   freeze. Confirm.
3. **Provider default** -- `claude-cli` assumed as default; confirm the Max
   plan is the intended payment path vs a metered key or local Ollama.
4. **taxonomy.yml home** -- tds-internal is the obvious private home; confirm,
   and whether the organized-output HTML should also be archived there as a
   dated backup.

### Reference input profile (2026-07-23 export)

Aggregate stats from the current real export (contents stay out of this
public doc; the file itself belongs in tds-internal if archived):

| Metric | Value | Design consequence |
|---|---|---|
| Bookmarks | 658 | Full tree (titles+URLs) fits one LLM context; `--restructure` is single-shot, no map-reduce needed. |
| Folders / max depth | 113 / 5 | Skeleton-with-counts prompt is small; depth cap not needed in v1. |
| Loose at roots | ~50 (22 in Other, 30 bar top-level) | Typical residue size per run: one or two LLM batches. |
| Exact-URL duplicates | 29 extra copies across 27 URLs; only 1 within a single folder | Validates per-folder dedupe scope: 28 of 29 are cross-folder breadcrumbs to keep. |
| Structure style | Topic folders already intent-adjacent | Migration is mostly rename/regroup, not from-scratch; churn minimizer matters. |

---

## Rejections

- **Dual top-level roots (ops/ vs ref/ as peer modes)** -- forces a mode
  declaration on every filing and every hunt; instead the intent tree stays
  primary and reference is one exhaustive generated subtree.
- **Chrome extension form factor** -- store review, permissions surface, and
  no filesystem/YAML access; the batch CLI fits the export/import workflow.
- ~~**Writing Chrome's `Bookmarks` JSON in place**~~ -- rejected for v1 for
  want of a backup story; **adopted 2026-07-30** as `orgmarks sync` now that
  there is one. What changed: the `SingletonLock` guard makes "Chrome is
  closed" a checked precondition rather than an assumption, atomic rename
  plus an out-of-tree backup makes a torn write unrepresentable, and GUID
  preservation turns the sync propagation from delete+create into moves.
  The original objection was correct; it was a missing-mechanism objection,
  not a never.
- **`SIGKILL` as a quit escalation** -- the obvious way to honor
  `--quit-timeout`, and it manufactures exactly the corrupted profile the
  guard exists to prevent. A Chrome that will not exit gracefully is a
  human's problem; orgmarks aborts and says which profile is stuck.
- **Re-checking `SingletonLock` as the pre-write safeguard** -- reads as
  sufficient and is a TOCTOU check, not exclusion: a Chrome launched in the
  gap between check and `rename()` still clobbers. Claim and hold the lock
  instead. Recorded because "just re-check right before the write" is the
  intuitive fix and it does not work.
- **Loading before quitting Chrome** -- the ordering that keeps the browser
  usable during the classify stage, at the cost of planning from a snapshot
  Chrome can still append to. Chrome flushes on exit, so a bookmark added
  or synced mid-run is written to disk at QUIT and then overwritten by the
  stale plan: silent loss, propagated fleet-wide. Quit first and accept the
  longer downtime.
- **Post-rename verification as the fallback for a breakable lock** -- it
  reads as defense in depth and is not: Chrome can break the lock and load
  the old tree before the rename, pass verification, and overwrite from
  memory afterward. Verification detects one failure mode. If the lock
  proves breakable the mechanism gets replaced, not backstopped.
- **Recomputing Chrome's `checksum` field** -- chases an internal algorithm
  across releases to avoid an ID reassignment that costs nothing, because
  node IDs are not identity in Chrome. Omit the key instead.
- **Backups inside the user-data-dir** -- convenient and puts unknown files
  where Chrome may enumerate, sync, or garbage-collect them. Backups live
  under `XDG_STATE_HOME`.
- **Driving `chrome://bookmarks` import via chrome-mcp automation** -- adds a
  browser-automation dependency to save one manual click; fragile against
  Chrome UI changes.
- **Adopting buku (or any manager) as backend** -- forces a second system of
  record; the whole point is Chrome stays canonical.
- **Pure-LLM classification every run** -- non-deterministic tree churn and
  linear cost in collection size; rules-first with learn-back gives the same
  coverage at converging cost.
- **Embedding/semantic-clustering pipeline (v1)** -- heavier machinery than
  needed while titles+URLs+hints classify well; reconsider if LLM batch
  classification proves weak on terse titles.
- **SQLite state between runs** -- taxonomy.yml already carries the only
  state worth keeping (learned rules); a DB adds a sync problem with the
  YAML.

---

## Future Considerations

- **Dead-link sweep** -- optional `--check-links` stage marking 404s into
  `_triage/dead`; deferred for network cost.
- **Scheduled grooming** -- a Routine that reminds (not auto-runs) when the
  unfiled count in a fresh export exceeds a threshold.
- **Other browsers** -- Firefox/Safari export both speak Netscape HTML;
  support is likely free but untested.
- **Title enrichment** -- fetching page titles for URL-shaped bookmark names
  before classification; network-bound, so batched and cached if added.
- **Other Chromium profiles** -- Brave/Edge/Vivaldi use the same `Bookmarks`
  JSON and the same `SingletonLock`; `sync` is likely near-free for them
  once the browser binary and data-dir resolution are table-driven.
- **Sync-aware dry run** -- ask Chrome Sync what it *would* propagate before
  writing. No supported API for it today; noted because the blast radius is
  the scariest part of `sync`.

---

## Related Documents

- [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md) -- provider rings
  referenced by the Classifier port.
- [LOG-HOARDER.DESIGN.md](./LOG-HOARDER.DESIGN.md) -- precedent for a
  top-level tool directory with a bin/ shim.
- [TEMPLATE.md](./TEMPLATE.md) -- section structure followed here.
