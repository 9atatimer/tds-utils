# Bookmark Organizer (orgmarks)

> **Status:** REVIEW
> **Date:** 2026-07-23
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
| Netscape HTML out | `bookmarks-organized-<date>.html`, importable via `chrome://bookmarks` Import. v1's only write path for bookmarks. |
| Plan report | Human-readable summary to stdout: N moved, N deduped, N triaged, folders created/removed, learned rules added. |
| Taxonomy write-back | Appends learned rules to `taxonomy.yml`, preserving comments and key order (ruamel-style round-trip parse); only on `apply`. |

Import caveat (documented in `--help` and the report): Chrome imports into an
`Imported` folder; the manual step is import, spot-check, delete the old
roots, drag the new tree up. Direct profile-write would remove this step but
is rejected for v1 (see Rejections).

### CLI

```
orgmarks plan  [--input FILE | --from-profile [NAME]] [--taxonomy FILE] [--restructure]
orgmarks apply [same flags]

plan:  read-only everywhere; prints the Plan.
apply: writes the output HTML and appends learned rules to taxonomy.yml.

Errors:
  input unparseable        -> exit 2, no output written
  taxonomy invalid         -> exit 2, Pydantic error listing
  LLM provider unreachable -> warn, degrade to rules-only, residue to _triage, exit 0
```

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
| PLAN | EMIT | mode == apply | `plan` mode stops here and prints |

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
- **Profile reads are read-only.** `--from-profile` opens Chrome's
  `Bookmarks` file read-only; v1 never writes into the profile directory.

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
- **Writing Chrome's `Bookmarks` JSON in place** -- eliminates the import
  step but races Chrome Sync and requires Chrome to be closed; one corrupted
  profile outweighs the convenience. Revisit post-v1 with a backup story.
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
- **Profile write-back** -- direct `Bookmarks` JSON emit (Chrome closed,
  timestamped backup, GUID preservation) to remove the import step.

---

## Related Documents

- [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md) -- provider rings
  referenced by the Classifier port.
- [LOG-HOARDER.DESIGN.md](./LOG-HOARDER.DESIGN.md) -- precedent for a
  top-level tool directory with a bin/ shim.
- [TEMPLATE.md](./TEMPLATE.md) -- section structure followed here.
