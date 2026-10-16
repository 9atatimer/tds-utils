# Dynomark -- live AI filing for native browser bookmarks

> **Status:** APPROVED; body amended 2026-10-16 on the owner's ruling to
> the as-built shapes (issue #424 and the 2026-10-16 Key Decisions rows).
> **Date:** 2026-09-26
> **Approved:** 2026-09-27 (Todd; rulings folded, see Key Decisions). Body frozen
> except by the owner's amendment.
> **Authors:** Todd + Claude
> **Depends on:** [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md)
> **Origin:** "Dynomark -- Product Proposal" (2026-09-25, PDF, not in repo);
> the review that produced this record is summarized in Key Decisions.
> **As-built:** `docs/arch/` does not exist in this repo yet; the only
> shipped related component is orgmarks (`bookmark-organizer/`). Until
> Dynomark's as-built lands at release, the wire is specified by
> `dynomark/contract/v2/README.md`.

---

## Overview

Bookmarks pile up unfiled and unfindable, and every AI bookmark tool fixes
that by moving the links into its own app. Dynomark keeps the browser's
native bookmark tree as the only interface: a page saved into `Follow Up`
with the normal bookmark dialog is captured, summarized and embedded by a
local daemon, then filed by a thin extension into a `Dynomark` folder the
tool maintains, with an address-bar keyword for fuzzy and semantic search
and a chat grounded in the corpus. Because the filed tree is plain synced
bookmarks, a phone saves into it and browses it with nothing installed.

---

## Goals

Scope is cut in two. **PoC** is the live loop on one laptop: ingest,
capture, place, file, tier-1 and tier-2 search, undo. **MVP** adds chat,
diffs (audit and rebuild), writer-conflict detection, background-tab
capture and Firefox. Goals 5 and the diff parts of 3 and 8 are MVP; the
rest are PoC.

- **Goal 1: Zero-friction capture** -- saving into `Follow Up` with the native
  bookmark dialog is the entire ingest gesture, from any signed-in device
  including a phone. No extension popup is required to save.
- **Goal 2: Live filing** -- on the writer host, the interval from the daemon
  receiving an ingest request to the extension's `APPLIED` receipt for
  that entry is under 60 s at P95 (daemon up, local models warm), and the
  browser is never closed for it.
- **Goal 3: Stable structure** -- a filed bookmark's folder changes only by a user
  move, an accepted `DiffItem`, or an undo. `place` is a pure function of
  (entry, neighbours, outline, feedback, completion output): with a fake
  `CompletionPort` returning a fixed answer, two calls give one placement.
- **Goal 4: Fast recall** -- tier-1 suggestions render within 20 ms (P95) of a
  keystroke at 10,000 entries; tier-2 hits arrive within 500 ms (P95) and
  include an entry whose only match is in captured page text.
- **Goal 5: Grounded chat** -- an `Answer` cites `CorpusEntry` identities that the
  retrieval step returned; an identity the completion invents is dropped;
  a URL outside the corpus is marked `external`, whether the completion
  lists it or only writes it in the answer text.
- **Goal 6: Undoable, never destructive** -- every `APPLIED` batch has an inverse
  that reverts each of its operations whose node is still where the batch
  left it, skips and reports the rest, and never hard-deletes: a removal
  is a move to `Graveyard`.
- **Goal 7: One writer** -- no browser profile other than the one a `writer`
  daemon is bound to is served a `WriteBatch`; a `Follow Up` save is filed
  by exactly one profile on one host; edits arriving from other devices
  or profiles are user edits.
- **Goal 8: Ownership boundary** -- a `WriteBatch` whose operations target a path
  outside `OwnedRoots`, unless every such operation lies inside the
  `Scope` of one accepted `DiffItem`, cannot be constructed: `file` and
  `accept_diff_item` raise before a batch exists. The extension checks
  every batch against the same rule before it touches the tree.

---

## Non-Goals

- **A standalone bookmark app or read-it-later reader** -- the native tree
  is the interface; a second place to live is the thing being avoided.
- **Mobile capture or processing** -- mobile browsers run no extension and
  no daemon. A phone saves into `Follow Up` and browses `Dynomark`.
- **Team or shared collections** -- single user, single sync account.
- **Automatic merging into the user's own bookmark bar** -- audit is
  suggest-only, one accepted item at a time.
- **Dead-link checking and page archival** -- orthogonal, network-bound;
  deferred.
- **Replacing orgmarks' batch export/import workflow** -- orgmarks is not
  modified by this record; its retirement is a separate decision.
- **Arbitrating two hosts both configured as writer** -- never resolved
  automatically. PoC: a `HostRole` flag and no detection. MVP: refuse on
  a writer marker in the owned tree (Key Decisions).

---

## Architecture Overview

Two runtimes, one ubiquitous language. The extension runtime is short-lived
and keeps only what an at-least-once path needs (The extension); the
daemon runtime holds everything durable. Dependencies point inward in
both: adapters -> application -> domain.

```
              user: Ctrl+D into "Follow Up"           user on any device,
                          |                            phone included: reads
                          v                            "Dynomark" via sync
  +-------------------------------------------+               ^
  |   browser bookmark tree (one profile)     |<--------------+
  |  Follow Up | Dynomark | Graveyard | rest  |     browser sync
  +----------+--------------------------------+
             | created / moved           ^ create/move/remove
             v                           |
  +----------+---------------------------+----+
  |  EXTENSION RUNTIME (Chrome or Firefox)    |
  |  watch Follow Up; capture from an open    |
  |  tab or, on the writer, a vetted          |
  |  background tab; apply batches; report    |
  |  moves; tier-1 search; chat surface       |
  |  (a page on Chrome, the sidebar on        |
  |  Firefox); settings and status            |
  +----------------+--------------------------+
                   | native-messaging shim -> unix socket
                   v   (contract v2, one profile per connection)
  +----------------+--------------------------+
  |  DAEMON RUNTIME                           |
  |  durable jobs; writer binding; URL vet;   |
  |  fetch fallback; enrich and index; place; |
  |  file; receipts; undo; diffs; chat;       |
  |  move feedback; re-embed; retention       |
  +----------------+--------------------------+
                   |
        +----------+-----------+
        v                      v
  local or cloud         corpus store on disk
  embedding/LLM          (owner-only, one per daemon)
  (model id at edge)
```

**Core (stable, in the problem's language):** the tree and `OwnedRoots`;
`Placement` and its reason; `WriteBatch`, its revert steps and its
`Scope`; ranking and fusion; `TreeDiff`; the address policy. None of these
know a browser API, a wire format, a vendor, a model id, or a database.

**Edges (volatile, one seam each):** the seam table under Design.

---

## Design

### Ubiquitous language

| Term | Meaning |
|---|---|
| `Bookmark` | A URL plus title at a `FolderPath`, with a per-profile `NodeId` and a cross-host `Identity` |
| `Identity` | The normalized URL. Normalized on the daemon only; the extension sends the raw URL |
| `FolderPath` | Ordered folder names from a root |
| `OwnedRoots` | The three folder names Dynomark owns (`Follow Up`, `Dynomark`, `Graveyard`), a value passed to the boundary policy, not a literal inside it |
| `TreeOutline` | The folder skeleton of the owned subtree with pin/lock flags and per-folder item counts; no URLs |
| `pinned` | A folder immune to `rebuild` and `audit` moves; still a placement candidate. Kept by folder path |
| `locked` | A folder excluded from placement candidates and never moved, renamed or merged by any batch. Kept by folder path |
| `Profile` | One browser profile the extension runs in, named by a random id the extension mints once and keeps in its settings. The transport connects per profile |
| `Capture` | Readable text plus title for a bookmark, with `source` in {`tab`, `background_tab`, `fetch`, `none`}; extraction to readable text is the content adapter's job |
| `Save` | One ingest as received: the bookmark as saved and its capture |
| `CorpusEntry` | A bookmark plus capture, summary, tags and embedding; the unit of search and retrieval |
| `Placement` | The folder chosen for an entry plus a `PlacementReason` (folder, neighbours, rationale, feedback ids, model id). A user move inside `Dynomark` replaces it with one whose reason says the user moved it |
| `Move` | An observed tree move with `origin` in {`extension`, `user`}; the extension adapter sets `origin` from the batch operations it itself issued |
| `MoveFeedback` | A `Move` of origin `user` of a bookmark between two owned folders, observed for the profile the writer is bound to, kept as a labelled example. The daemon alone decides it |
| `Operation` | One of create-folder-at-path, create-at-path, move-to-path, remove-to-graveyard; each is path-idempotent (create if absent, move if not already there) |
| `WriteBatch` | Ordered `Operation`s plus their revert steps, a `BatchId`, the profile it is for, and optionally an accepted `DiffItem` reference with its `Scope`, or a `ParkReason` |
| `Revert step` | One step of a batch's inverse: revert operation i, a created node to `Graveyard`, a moved or removed node back to the folder it left. It names an operation, not a node; it is made concrete into `Operation`s at a receipt or an undo, against the tree read then |
| `ParkReason` | Why a batch parks its node instead of filing it: the folder the existing filed copy of its identity sits in now |
| `Scope` | The folders an accepted `DiffItem`'s operations target or take a node from. A scope path admits only itself, never what lies under it |
| `BatchReceipt` | The extension's answer for a batch: `APPLIED` with an outcome per operation (applied with its node id, or skipped with a reason), `PARTIAL` with the applied prefix and the failed operation, or `REJECTED` with a reason; carries the tree read at the start of the apply attempt |
| `Snapshot` | The full tree as the extension read it at the start of an apply attempt; the fallback export, not the undo mechanism |
| `Latest tree` | The newest full tree a profile reported. The writer-bound profile's is what filing, outlines and the undo guard read; each reader-served profile's is kept for retention only |
| `Job` | The durable unit of daemon work for one ingested save, one per (`Profile`, `NodeId`, `Identity`); see State Machine |
| `RetryPolicy` | Attempts and backoff for retryable job errors; a parameter of the daemon `Config` |
| `HostRole` | `writer` or `reader`, as served to one profile. A daemon configured `writer` serves the profile it is bound to as `writer` and every other profile as `reader`; a daemon configured `reader` serves every profile as `reader` |
| `WriterBinding` | The profile a `writer` daemon files for: the first to complete a full handshake. The owner releases it on the daemon; the next full handshake binds |
| `NotWriter` | The non-retryable result a write-producing use case returns when the profile is served `reader` |
| `WriterConflict` | The result on a writer that sees another host's writer marker in `Dynomark`: it files nothing, applies no batch, and says which host |
| `Address policy` | Which addresses a URL's host may resolve to before anything loads it, from the daemon or with the user's session: public addresses only, unless `Config` opts out for both paths at once |
| `Model mark` | Whether a model is `local`: only when its server is on loopback, its id carries no cloud tag, and `Config` does not declare the endpoint remote |
| `Query` / `Hit` | A search string; a ranked match with `tier` in {`local`, `corpus`} and a score |
| `LocalIndex` | Per entry: identity, title, path, tags, one-line summary; at most 512 bytes per entry; pulled from the daemon, held by the extension |
| `Frecency` | A map identity -> visit boost derived from browser history through `HistoryPort` |
| `Turn` / `Question` / `Answer` / `Citation` | One chat exchange; the user's text; the grounded reply; a reference to a `CorpusEntry` identity |
| `RequestId` | The caller-chosen id of one transport request; the delivery guarantee keys on it |
| `DiffKind` | `audit` or `rebuild` |
| `TreeDiff` / `DiffItem` | A proposed set of folder adds and moves with `kind` in {`audit`, `rebuild`}; one line of it. Merges are not proposed for MVP. An item is *accepted* when `accepted_at` is recorded |
| `Config` | The daemon's settings: `HostRole`, model ids and whether their endpoint is declared remote, store path, `RetryPolicy`, rebuild cadence, the address policy's opt-out, retention. The extension owns only transport selection, its profile id and the capture and `Follow Up` behaviour |

### Seams (axes of change)

| Axis of change | Seam | Implementations (now / plausible) |
|---|---|---|
| Browser tree API (Chrome, Firefox) | `BookmarkTreePort` | Chrome adapter and Firefox adapter, both built |
| Browser history (frecency source) | `HistoryPort` | Chrome adapter and Firefox adapter, both built |
| Extension <-> daemon transport | `TransportPort` | native-messaging shim over a unix socket / HTTPS behind the Access gate for a phone client |
| Where page content comes from | `ContentSourcePort` | open-tab extractor and background-tab extractor (extension) / fetch-and-extract (daemon); a fallback chain, not a swap |
| Corpus store | `CorpusStorePort` | SQLite with FTS5 and a vector extension (production) / in-memory fake (tests) |
| Embedding vendor and model | `EmbeddingPort`, model id at the edge | local (Ollama) / cloud |
| Completion vendor and model | `CompletionPort`, model id at the edge | local (Ollama) / Anthropic / OpenAI |

The daemon's implementation language is not a seam; it is free because the
transport contract is a versioned schema artifact in the repo that both
runtimes' adapters are generated from or validated against (Key Decisions).

### The extension

| Responsibility | Details |
|---|---|
| Watch `Follow Up` | On a create or move into `Follow Up`, run `capture` and `submit_save`. Zero folders named `Follow Up` at startup: create one under the bookmarks bar. More than one: use the one under the bookmarks bar and report the others. |
| Capture from the open tab | If a tab shows the saved URL, the tab adapter returns readable text with `source` `tab`. Otherwise, on a profile served `writer` with the background setting on (the default), the extension asks the daemon to vet the URL against the address policy and, only on an allow, reads it from a background tab with `source` `background_tab`. A refusal, an error or no answer opens no tab. Anything not captured goes with `source` `none`, and the daemon fetches it. Content is read only for a save; it needs the browser's all-sites host permission (Key Decisions). |
| Apply write batches | `apply_batch`: read a `Snapshot`, check every operation against `OwnedRoots` or, for an accepted item's batch, its `Scope`, and refuse a batch on a writer marker of another host; then apply operations in order through `BookmarkTreePort`, recording each outcome in the batch cursor; return a `BatchReceipt`. A batch already fully applied (by cursor or by batch id) is answered `APPLIED` again without touching the tree. |
| Record feedback | Report every `Move` whose source and destination are owned, with its origin. Whether it is `MoveFeedback` is the daemon's decision alone; the extension holds no copy of the rule. |
| Backfill | Started by the user from the settings page: the existing tree is ingested as a backfill at a bounded rate, with no capture, so the daemon fetches. Nothing it sends is re-filed. |
| Tier-1 search | `search_local` over the `LocalIndex` and `Frecency`. Title matches form a hard tier above path, tag and summary matches; within a tier, fuzzy score with a bounded boost for entries filed under `Dynomark`, then frecency. No transport call. |
| Tier-2 search | `search_remote` when tier-1 returns fewer than `tier2_min_hits` hits or the best score is under `tier2_min_score` (named parameters, values in code); hits append below tier-1. |
| Ask fall-through | The last suggestion is always `Ask: <query>`; entering it, or entering with no hit, opens the chat surface with the query pre-sent. |
| Chat surface | An extension page on Chrome; the sidebar on Firefox. It is a view, not a composition root: it sends `Question`s to the background context and renders `Answer`s, `Citation`s, "file this" and "why here". It names both models with their `Model mark`s, and warns when either sends data off the machine. Conversation state lives in the page. |
| Settings | Transport selection, the profile id, and the capture and `Follow Up` behaviour, in extension-local storage; nothing secret. The settings page shows the daemon's role for this profile, says when this browser is served `reader` because the writer is bound to another profile, and shows a writer conflict. |

Every extension operation is short and path-idempotent, because its
runtime can be terminated between any two events.

Durable extension state is a rule, not a list: it holds whatever an
at-least-once path needs to survive that termination, and nothing else.
As built that is the settings, the rebuildable `LocalIndex`, the in-flight
batch cursor, and the saves, moves and background captures not yet
answered by the daemon. Captured page text is kept only until the daemon
acknowledges its save, or refuses it for good (Key Decisions "Extension
durable state", 2026-10-16).

### The daemon

| Responsibility | Details |
|---|---|
| Process lifetime | The daemon is long-lived and reached over a unix socket with owner-only permissions; the native-messaging host is a shim that forwards one browser connection to it. Jobs run whether or not an extension is connected. |
| Writer binding | A daemon configured `writer` binds to the first profile that completes a full handshake and serves every other profile as `reader`. The owner releases the binding with a command on the daemon; the next full handshake binds. The status a profile reads says whether the writer files for it, for another profile, or for none yet. |
| Durable jobs | One `Job` per (`Profile`, `NodeId`, `Identity`), persisted with its `Save` before acknowledgement; retried per `RetryPolicy` on a retryable error, and failed at once on a non-retryable one; `NotWriter` is not retryable and not counted. |
| URL vetting | Before the writer's extension opens a background tab, the daemon judges the URL: http(s) only, and every address its host resolves to must pass the address policy. The daemon resolves DNS; the extension cannot. |
| Capture fallback | `capture` with the fetch adapter, only when the request's capture has `source` `none`; carries no cookies; skips non-http(s) URLs; connects only to an address the address policy allows; bounded in size and time. |
| Enrich and index | Summary, tags and embedding through the ports; full-text and vector indexing through `CorpusStorePort`. Hybrid fusion runs in the domain over the two candidate lists the store returns. |
| Models | Model ids are supplied at the edge. Each model carries its `Model mark`, and the status reports both. Nearest-neighbour search compares only entries embedded by the current embedding model; after a model change the corpus is re-embedded in the background, a bounded pass at a time, and an entry not yet re-embedded is found by full-text search alone. |
| Place and file | `place` chooses a folder and records the reason; `file` turns the placement into a `WriteBatch` (with its revert steps) that the boundary policy has admitted, stores it `PROPOSED`, and offers it to the writer-bound profile. The batch's move consumes the `Follow Up` node; nothing remains there. |
| Duplicate identity | An identity counts as already filed only when a `FILED` job of it has its node in the latest tree outside `Graveyard`. Such an ingest files nothing new: the new node is moved to `Graveyard` by a batch whose `ParkReason` names the folder the existing copy is in. A parked copy never makes a later save a duplicate. |
| Backfill | A backfill job is never offered a batch. On the writer, one whose bookmark is already inside `Dynomark` records its placement where it sits and ends `FILED`; every other ends `INDEXED`. This is how a new writer learns what is already filed. |
| Receipts | `APPLIED` with the filing operation applied: store node ids and the snapshot, job `FILED`. `APPLIED` with the filing operation skipped, or `PARTIAL`: store the snapshot, offer the inverse of the operations that changed the tree as a new batch, job `FAILED`. `REJECTED`: job `FAILED`. A receipt is recorded on whichever connection it arrives; an inverse is minted only on a connection served `writer` for the batch's own profile. A batch too large to offer is `REJECTED` by the daemon without a receipt, and its job `FAILED`. |
| Undo | `undo` makes the revert steps of an `APPLIED` batch concrete against a tree read after its receipt, and answers busy until one has arrived. It is guarded: a step is kept only if its node is still where the batch left it, a folder removal only if the folder is empty, never a step that moves a `locked` folder, and never one that removes an owned root the batch created. The rest are dropped and listed in the batch's report with their reason. The inverse carries the same `DiffItem` reference and `Scope` if the original had them. |
| Move feedback | The one rule: a `Move` of origin `user`, of a bookmark, between two owned folders, observed for the writer-bound profile, is `MoveFeedback`. A folder move, an `extension` move, and every move of a reader-served profile give none. A user move inside `Dynomark` also replaces the entry's `Placement`. |
| Diffs | `propose_diff` of kind `audit` (between `Dynomark` and the user's bar) or `rebuild` (a reorganized owned tree), on the writer only: a reader cannot apply a diff and has no channel to the writer. Items are folder adds and moves; merges are discarded. Rebuild is manual unless `Config` sets a cadence. Nothing is applied until a `DiffItem` is accepted; each acceptance is its own batch, carrying the item's `Scope`. |
| Chat | Retrieve top-k entries, answer through `CompletionPort`, keep only citations the retrieval returned, and mark `external` every out-of-corpus URL the completion lists or writes in its answer text. |
| Writer marker | The writer leaves a marker in `Dynomark`. A writer that sees another host's marker is in `WriterConflict`: an ingest is still indexed for search and chat and its job ends `FAILED` naming the conflict; undo, diff acceptance and flag changes are refused. |
| Retention | A corpus entry, its saves and its placement are dropped once its bookmark has been absent from every known profile's latest tree for the retention window. An archived snapshot is dropped once older than that window unless an undo needs it. Batch rows stay. Answered requests are dropped. |
| Config | Loaded once by the composition root as a `Config` value; `HostRole` is passed into use cases, never read from a global. |

### Transport contract (the load-bearing part only)

| Guarantee | Statement |
|---|---|
| Identity and version | The first exchange on a connection states a contract version on both sides and names the profile. On mismatch, write-producing flows stop; search and chat continue only if the extension's version is newer than the daemon's. The contract is a versioned schema artifact in the repo; version 2 is current. |
| Roles | A connection is served one `HostRole` for its whole life, decided by the writer binding at the handshake; the extension handshakes again to pick up a new binding. A connection served `reader` is never offered a batch, and readers do not propose diffs. |
| Direction | Extension -> daemon: requests with a caller-chosen request id. Daemon -> extension: responses by id, plus unsolicited events (job finished, batch ready). |
| Delivery | Requests are at-least-once from the extension; ingest is idempotent on (`Profile`, `NodeId`, `Identity`), and a move report is idempotent too. Events are durable on the daemon until acknowledged; on connect the extension asks for everything unacknowledged. |
| Partial failure | A batch is `PROPOSED` until a `BatchReceipt` arrives. An unacknowledged batch is re-offered on the next connect; the extension answers from its cursor without re-applying. |
| Boundary | A batch realizing an accepted `DiffItem` carries that item's `Scope`. The daemon constructs, and the extension applies, only operations inside `OwnedRoots` or that scope. |
| Background-tab vetting | The extension opens a background tab only on the daemon's allow for that URL; a refusal, an error or a lost link is a refusal. |
| Retryable errors | Transport loss and daemon restart are retryable by reconnecting. `REJECTED` and `PARTIAL` are not retried automatically; they surface in chat and the diff view. |
| Confidentiality | The transport never leaves the machine in v1. A remote adapter is a separate record and sits behind the fleet's Access gate. |

Message names, field shapes and serializers are the implementation's
business and are not pinned here.

### Placement policy (the rule, once)

- Nearest neighbours by embedding among already-placed entries, from
  `CorpusStorePort`, compared only against entries the current embedding
  model embedded.
- `CompletionPort` chooses an existing owned folder that is not `locked`,
  or proposes one new leaf under an existing owned folder, given the
  neighbours and their folders, the `TreeOutline`, and the most recent
  `MoveFeedback` examples.
- A proposed leaf that collides with an existing name at the same level
  resolves to the existing folder.
- A choice in or under a `locked` folder lands beside it: in a sibling of
  that folder, or in a new leaf under its parent. It never lands inside a
  locked folder.
- A choice outside `Dynomark` goes to the admissible folder most of the
  neighbours sit in, else the `Dynomark` root.
- The placement and its reason are recorded before `file` builds a batch.

These steps run in the order listed. Placement never moves an existing
item. Only an accepted `DiffItem` or an undo moves what is already filed.

### Multi-device policy

| Folder | Who writes | Who reads |
|---|---|---|
| `Follow Up` | any device adds (phone included); the writer moves items out | every host's daemon ingests from it |
| `Dynomark` | the writer only | every device, through sync |
| `Graveyard` | the writer only | every device |
| rest of the tree | the user; the writer only inside an accepted `audit` item | every device |

"The writer" is one host and, on it, the one profile its daemon is bound
to. One writer means no claiming and no cross-host de-duplication. A
profile served `reader`, on any host, has every save it sees ingested for
that daemon's own search and chat, keyed on the create event; the job
completes regardless of where the node moves afterwards.

Tab capture happens on the device where the save was made. The writer
captures a save made elsewhere from a background tab, only for a URL the
daemon vets; otherwise by fetch, which loses logged-in content (Key
Decisions "Background-tab capture", 2026-10-16). Changing the writer host
moves `HostRole` on two hosts; the new writer learns what is already filed
from a backfill, and undo does not cross a writer change.

### Module map (phase 3)

The module map, the ports each runtime wires, and each use case's
signature are the architecture record's and the as-built's, not this
record's (the design skill). No architecture record exists yet; until the
as-built lands in `docs/arch/` at release, read them from
`dynomark/daemon/src/dynomark_daemon/` and `dynomark/extension/src/`.

The domain is expressed twice because the runtimes cannot share a process;
the language is one, and each side tests its domain in isolation.

---

## Behaviors and Interfaces

One row per behavior; each is a kept test. Use-case signatures and the
ports each needs are not pinned here (Module map).

| Behavior | Given / When / Then |
|---|---|
| Content is captured from the open tab | Given a tab showing the URL, When captured, Then `source` is `tab` and text is non-empty |
| A background tab captures a vetted URL | Given the writer-bound profile, the background setting on, no open tab on the URL, and the daemon allows it, When captured, Then `source` is `background_tab` |
| A refused URL opens no background tab | Given the daemon refuses the URL, answers an error, or does not answer, When captured, Then no tab opens and `source` is `none` |
| Content falls back to fetch | Given a request whose capture has `source` `none`, When captured, Then `source` is `fetch`; if the fetch fails or the address policy refuses the address, `source` stays `none` and the job continues |
| A save is submitted | Given a new `Follow Up` node, When submitted twice, Then the daemon holds one job |
| Page text leaves extension storage on acknowledgement | Given a save in flight with captured text, When the daemon answers its ingest or refuses it for good, Then extension storage no longer holds that text |
| A save is ingested | Given a bookmark, When ingested, Then a `Job` is `QUEUED`; a second ingest with the same (`Profile`, `NodeId`, `Identity`) returns the same job |
| A duplicate identity is parked | Given an identity with a `FILED` job whose node is in the latest tree outside `Graveyard`, When the new node is ingested on the writer, Then the batch moves the new node to `Graveyard`, its `ParkReason` names the existing copy's folder, and the existing placement is unchanged |
| A parked copy is no duplicate | Given the only `FILED` copy of an identity sits in `Graveyard`, When a new save of it is ingested on the writer, Then it is placed and filed |
| A job is processed to an entry | Given a job with a capture, When processed, Then the entry has summary, tags and embedding and tier-2 search finds a word only in the captured text |
| A failed enrichment is retried, then parked | Given a completion that errors `RetryPolicy.attempts` times, When processed, Then the job is `FAILED` and no batch references its identity |
| An entry is placed | Given three placed neighbours in one folder and a fake completion echoing it, When placed, Then the placement names that folder and its reason lists the neighbours |
| Placement respects a lock | Given the fake completion names a `locked` folder or one under it, When placed, Then the result is a sibling of the locked folder or a new leaf under its parent, never inside it |
| Neighbours come from one embedding model | Given entries embedded by an earlier model, When placed or searched, Then nearest neighbours come only from entries of the current model; after re-embedding they come from all |
| A placement becomes a batch | Given a placement under `Dynomark`, When filed, Then a batch with create-folder, move and their revert steps exists in `PROPOSED` |
| An out-of-boundary batch is unconstructible | Given a placement path outside `OwnedRoots` and no accepted item, When filed, Then it raises and no batch row exists |
| A batch is applied | Given a batch, When applied, Then a snapshot is read first, operations run in order, and the receipt is `APPLIED` with an outcome per operation |
| An out-of-scope batch is refused by the extension | Given a batch with an operation outside both `OwnedRoots` and the batch's `Scope`, When applied, Then the receipt is `REJECTED` with reason boundary and the tree is untouched |
| A batch resumes after termination | Given a cursor at operation 3 of 5, When the same batch is offered again, Then operations 1-3 are not repeated and the receipt is `APPLIED` |
| A batch fails midway | Given operation 3 fails, When applied, Then the receipt is `PARTIAL` with the applied prefix |
| A receipt is delivered | Given a receipt, When delivered twice, Then the daemon records it once |
| A receipt is processed | Given `APPLIED` with the filing operation applied, Then the job is `FILED` and the snapshot stored; Given `PARTIAL`, or `APPLIED` with the filing operation skipped, Then the job is `FAILED` and a `PROPOSED` inverse of the changed operations exists |
| A receipt off the writer mints nothing | Given a receipt on a connection served `reader`, When processed, Then the batch takes its state and no inverse batch exists |
| A user move becomes feedback | Given a `Move` of origin `user` of a bookmark between owned folders, for the writer-bound profile, When reported, Then feedback exists; Given origin `extension`, a folder move, or a reader-served profile, Then none |
| A user move rewrites "why here" | Given a filed entry the user moves to another folder inside `Dynomark`, When reported, Then its placement names the new folder and its reason says the user moved it |
| Tier-1 search | Given 10,000 entries, When queried, Then every title match precedes every non-title match and the call is within Goal 4's tier-1 bound |
| Tier-2 search is requested | Given tier-1 returned under `tier2_min_hits`, When requested, Then hits have `tier` `corpus` |
| Tier-2 search | Given a word only in captured text, When queried, Then that entry is a hit, and fusion over the store's two candidate lists runs with a fake store |
| The local index is synced | Given a changed corpus, When synced, Then the index has one row per entry, each at most 512 bytes |
| The local index is built | Given the corpus, When built, Then rows hold exactly identity, title, path, tags, one-line summary |
| A question is answered with citations | Given a fake completion citing the retrieved identities, When asked, Then each is a `Citation`; Given it cites an identity not retrieved, Then that one is dropped |
| An out-of-corpus URL is marked | Given the completion lists a URL not in the corpus, or writes one only in its answer text, When asked, Then the answer marks it `external` |
| Both models are shown with their marks | Given a loopback model server serving a cloud-tagged model, or an endpoint `Config` declares remote, When the status is read, Then that model is not `local`, and the chat surface names both models and warns that data leaves the machine |
| A batch is undone | Given an `APPLIED` batch and a user edit to nodes the batch did not touch, When undone, Then the inverse batch reverts every operation and the user edit is not among its targets |
| Undo waits for a tree after the receipt | Given an `APPLIED` batch and no tree reported since its receipt, When undone, Then the answer is busy and no batch exists |
| Undo skips a moved or vanished node | Given one batch node was since moved or deleted by the user, When undone, Then that inverse operation is dropped and listed in the batch's report |
| Undo leaves a non-empty folder | Given a folder the batch created now holds other items, When undone, Then its removal is dropped and reported |
| Undo keeps a locked folder and the owned roots | Given a folder the batch moved is now `locked`, or the batch created `Dynomark` or `Graveyard`, When undone, Then that step is dropped and reported as locked or as an owned root |
| A diff is proposed | Given the two outlines on the writer, When proposed, Then items exist, each a folder add or move, and no batch exists |
| A reader proposes no diff | Given a profile served `reader`, When a diff is requested, Then it is refused and no diff exists |
| A diff item is accepted | Given an item with `accepted_at` set, When accepted, Then a batch exists referencing that item and carrying its `Scope`; Given `accepted_at` unset, Then it raises |
| An audit item may cross the boundary | Given an accepted `audit` item targeting the user's bar, When accepted, Then the batch is admitted and its inverse carries the same item reference and `Scope` |
| A placement is explained | Given a filed entry, When explained, Then the reason names the folder, neighbours and feedback used |
| A reader host never writes | Given a profile served `reader`, When placing, filing, undo or accepting a diff item runs, Then the result is `NotWriter` and no batch row exists |
| A writer files for its bound profile | Given a writer daemon bound to profile A, When profile B completes a handshake, Then B is served `reader`, its saves end `INDEXED`, and its status says the writer is bound to another profile |
| Rebinding moves the writer | Given the owner releases the binding, When the next profile completes a full handshake, Then that profile is served `writer` |
| A writer conflict files nothing | Given another host's writer marker in `Dynomark`, When a save is ingested on the writer, Then it is indexed, its job ends `FAILED` naming the conflict, and no batch is offered |
| A backfill records what is already filed | Given the writer and a backfilled bookmark already inside `Dynomark`, When processed, Then the job is `FILED` with no batch and its placement is where it sits; Given one elsewhere, or a reader-served profile, Then the job is `INDEXED` |
| A flag survives a rebind | Given a folder locked while profile A is bound, When the binding moves to profile B, Then the folder is still locked |
| A bookmark gone from the tree leaves the corpus | Given an entry whose bookmark has been absent from every known profile's latest tree for the retention window, When retention runs, Then the entry, its saves and its placement are gone and search does not return it |

---

## State Machine

The `Job` is the lifecycle-bearing entity.

```
 +--------+   +-----------+   +----------+   +--------+   +-------+
 | QUEUED |-->| CAPTURING |-->| ENRICHED |-->| PLACED |-->| FILED |
 +--------+   +-----------+   +----+-----+   +--------+   +-------+
      |             |              |              |
      |             |              +------------------------> +---------+
      |             |              |  (served reader, or a    | INDEXED |
      |             |              |   backfill not inside    +---------+
      |             |              |   Dynomark)
      +------+------+--------------+--------------+
             v  (see the FAILED row)
         +--------+
         | FAILED |----> QUEUED  (user retries)
         +--------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| QUEUED | CAPTURING | job picked up | any profile |
| CAPTURING | ENRICHED | capture resolved (`tab`, `background_tab`, `fetch`, or `none` after fetch gave up) and entry enriched | ports returned |
| ENRICHED | INDEXED | entry indexed | the profile is served `reader`, or the job is a backfill whose bookmark is not inside `Dynomark`; terminal; `place` is not called |
| ENRICHED | PLACED | placement recorded | served `writer`; a backfill inside `Dynomark` records its placement where it sits |
| PLACED | FILED | an `APPLIED` receipt whose filing operation applied; for a backfill, at once with no batch | terminal |
| QUEUED, CAPTURING, ENRICHED, PLACED | FAILED | retries exhausted; a non-retryable error; a writer conflict; a `PARTIAL` or `REJECTED` receipt; an `APPLIED` receipt whose filing operation was skipped; a batch too large to offer | node stays where it is; on `PARTIAL` or a skipped filing an inverse of the changed operations is offered |
| FAILED | QUEUED | user retries from chat or menu | allowed while the job's save is kept; once retention has dropped it, the retry is refused |

A batch has its own states, `PROPOSED -> APPLIED | PARTIAL | REJECTED`, in
the transport contract; a batch too large to offer is `REJECTED` by the
daemon with no receipt. A `DiffItem` is `proposed -> accepted`.

---

## Data Model

Logical model; the physical schema is the implementation's business.

```
bookmark                as one profile sees it
+-- identity          normalized URL (cross-host identity)
+-- node_id           per-profile browser node id
+-- title, url, folder_path, date_added

save                    one ingest as received, per job
+-- job, bookmark, capture

capture
+-- source            tab | background_tab | fetch | none
+-- text, title

corpus_entry
+-- identity          unique
+-- summary, tags[]
+-- embedding         vector, with the model id that produced it

placement
+-- identity
+-- reason            folder, neighbours, rationale, feedback ids, model id
+-- created_at

folder_flags
+-- folder_path, pinned, locked

move_feedback
+-- feedback_id, identity, from_path, to_path, observed_at

job
+-- job_id, profile, node_id, identity, state, attempts, last_error
+-- backfill, capture source, batch or none, updated_at

tree_diff
+-- diff_id, kind (audit | rebuild), proposed_at

diff_item
+-- item_id           FK tree_diff
+-- operations[], accepted_at or none

write_batch
+-- batch_id, profile, operations[], revert steps[]
+-- state             PROPOSED | APPLIED | PARTIAL | REJECTED
+-- receipt           an outcome per operation, or the applied prefix and
|                     the failed operation, or a reason
+-- park reason or none; diff_item_id and scope, or none
+-- undoes / undone by, or none
+-- snapshot_id or none
+-- report            revert steps dropped by the undo guard, with reasons

latest tree             one per profile that reported one
+-- profile, taken_at, tree

snapshot                archived per receipt (fallback export)
+-- snapshot_id, taken_at, tree

writer binding          the profile a writer daemon files for, or none
event                   per profile, durable until acknowledged
answered request        so a repeated request id is answered alike
absence                 when an entry's bookmark was first found absent
                        from every latest tree

extension-side          the durable-state rule (The extension)
```

Constraints: one `corpus_entry` per `identity`; one `job` per (`profile`,
`node_id`, `identity`); every `write_batch` operation targets a path under
`OwnedRoots` unless `diff_item_id` names an item with `accepted_at` set
and every such operation is inside that item's `scope`; folder flags are
keyed by folder path, never by a profile's node ids.

---

## Data Warehouse

Nothing is ledgered. Dynomark is a single-user, laptop-resident tool; its
write log and snapshots are product state kept for undo, bounded by
retention, live only in the local corpus store, and are not exported to
any fleet ledger.

---

## Parameters

Every bound the body names, and what constrains it. Values are tuned and
live in the code until the as-built records them.

| Parameter | Bounds | Constraint |
|---|---|---|
| `tier2_min_hits`, `tier2_min_score` | when tier 2 is asked | tier 2 is asked only when tier 1 is thin or weak |
| Tier-1 filed-entry boost | how far an entry under `Dynomark` moves up within its tier | reorders within a tier only; never lifts a non-title match above a title match |
| `RetryPolicy` | attempts and backoff per job | finite attempts; backoff grows and is capped; exhaustion fails the job |
| Backfill rate | ingests per unit time during a backfill | bounded; a backfill is started by the user only |
| Rebuild cadence | how often a `rebuild` diff is proposed unasked | off unless `Config` sets it |
| Re-embed pass | entries re-embedded per pass after a model change | bounded, so a pass never holds the store for the whole corpus |
| Retention window | how long an absent bookmark's entry, saves and placement outlive it, and how long an archived snapshot is kept | finite; an archive an undo needs is kept regardless |
| Capture bounds | size and time of one fetch, size of captured text | bounded on both runtimes |
| Pending-save bound | saves and captured text kept in extension storage | bounded; a save that cannot fit alone is still sent, just not kept |
| Address policy opt-out | whether private addresses may be loaded | off by default; when on, it applies to fetch and background tab alike |

---

## Security Considerations

- **All-sites host permission** -- required so the extension can read the
  DOM of the tab that shows a just-saved page (logged-in and paywalled
  content), and on the writer a background tab for a save no open tab
  shows. Mitigation: the extension is self-installed and unpacked, not
  store-listed; content is read only in response to a save into
  `Follow Up`, never on navigation; non-http(s) URLs are never captured;
  a background tab opens only for a URL the daemon vets.
- **Other extension permissions** -- browser history (frecency), tabs
  (finding the tab that shows a saved URL, and the background tab),
  scripting (reading that tab) and unlimited storage (the durable state).
  Mitigation: each serves one responsibility above; none is used on
  navigation.
- **A background tab carries the user's session** -- a URL synced in from
  another device would otherwise make the writer's browser load loopback,
  router or intranet pages with its cookies. Mitigation: the daemon vets
  every such URL with the address policy that also governs its fetch;
  anything but an allow opens no tab.
- **Page content of logged-in sessions on disk** -- the corpus store holds
  captured text, and extension storage holds a save's captured text until
  the daemon acknowledges it. Mitigation: the corpus store has owner-only
  permissions in the user's state directory; it is never synced or backed
  up by Dynomark and excluded from any repo; extension storage keeps page
  text only until the save is answered, inside the browser profile; an
  entry whose bookmark has left every known tree is dropped, its text with
  it, after the retention window.
- **Cloud model egress** -- summaries, page text and questions may leave
  the machine, through either model. Mitigation: model choice is per
  install and per port, local is the default, and a model is marked
  `local` only under the `Model mark` rule; the chat surface names both
  models with their marks and warns when either sends data off the
  machine.
- **Transport exposure** -- the native-messaging shim is bound to the
  extension's identity in the host manifest; the daemon's unix socket is
  owner-only; no TCP port. A remote adapter is a separate record behind the
  Access gate.
- **Tree damage** -- the boundary policy runs before a batch exists, and
  the extension runs it again, with the batch's `Scope`, before it touches
  the tree; every batch has recorded revert steps and a preceding
  snapshot; removals go to `Graveyard`; operations are path-idempotent so
  a resumed batch cannot double-create.
- **Daemon-side fetch** -- carries no cookies, follows the same
  non-http(s) exclusion, and connects only to addresses the address policy
  allows.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Source of truth | the native browser bookmark tree | no new app to live in; sync to every device, phone included, comes free |
| Process split | thin extension owns tree writes; long-lived daemon owns capture, corpus, models | the extension runtime cannot run long jobs; a daemon behind a native-messaging shim can, whether or not the browser is connected |
| Multi-device | one shared `Dynomark` folder, one `writer` host | per-host folders duplicate the hierarchy on every device and force a claiming protocol; one writer needs neither |
| Phone | a consumer: saves into `Follow Up`, reads `Dynomark` via sync | mobile browsers run no extension; this gives capture and browse with zero mobile software |
| Corpus locality | one corpus per daemon; only the writer files | local search and chat on every laptop without a corpus sync problem |
| Tab capture locality | tab capture only where the save happened; the writer fetches saves made elsewhere | there is no cross-host channel; the logged-in loss for saves made on a reader device or phone is accepted for PoC; the MVP answer is a background-tab capture adapter on the writer (Future Considerations) |
| `Follow Up` semantics | consumed on filing: the batch moves the node into `Dynomark`; the filed copy is the record | a queue, not a to-do; to-do states (new, read, done) were the alternative and are not built |
| Two writers | PoC: `HostRole` is a config flag with no detection; MVP: refuse on a writer marker in the owned tree | concurrency is not a PoC problem; refusing beats last-wins because a silent second writer is the conflict the design removes |
| Scope | PoC = ingest, capture, place, file, tier-1/tier-2 search, undo; MVP = chat, diffs, writer-conflict detection, background-tab capture, Firefox | get the live loop working on one laptop before any concurrency or reach work |
| Approval | APPROVED 2026-09-27 | rulings 1-3 of the 2026-09-27 review folded above; body frozen from this commit |
| Transport | `TransportPort`; native-messaging shim over a unix socket first | no TCP port, no pasted token, the browser launches the shim; a phone adapter is a second implementation |
| Daemon language | unconstrained; the contract is a versioned schema artifact | any process that validates against the schema is the daemon; hot-swappable |
| Content capture | all-sites host permission, daemon fetch as fallback | the only way to capture logged-in pages at save time |
| Extraction | inside the `ContentSourcePort` adapters | readable-text extraction is a vendor choice per side; the core sees `Capture` |
| Undo | guarded inverse of a recorded operation log per batch | snapshot replay cannot preserve unrelated later edits; a guarded inverse can |
| Batch operations | path-idempotent, with an extension-side cursor | the extension can die mid-batch; re-offer must not double-create |
| Placement | incremental, embedding neighbours + completion + feedback; rebuild only via accepted items | stability over cleverness; a tree that reshuffles is not trusted |
| Deletions | `Graveyard`, emptied by hand only | no hard delete path exists to get wrong |
| Audit and rebuild | one `TreeDiff` mechanism, kind-tagged; acceptance recorded per item | one boundary exception path, enforced by data, not by caller discipline |
| Embedding and completion vendors | `EmbeddingPort`, `CompletionPort`; model ids at the edge | local by default, cloud by choice, no vendor in the core |
| Corpus store | `CorpusStorePort`; SQLite with FTS5 and a vector extension is the only production adapter | the same port shape SEMANTIC-SEARCH names; use cases stay testable with an in-memory fake |
| Hybrid ranking | fusion in the domain over the store's two candidate lists | testable without the store |
| Relation to orgmarks | supersedes it for the live flow; orgmarks untouched | orgmarks required off-lining the browser and went unused; this record overturns its rejections that only held for a batch tool (Rejections) |
| Tech radar | `sqlite-vec` is Assess on `lmde/TECH_RADAR.md`; propose Trial with this record | first production use in the fleet; SEMANTIC-SEARCH already names it |
| KNN engine (2026-10-05) | `sqlite-vec` loaded on every store connection; KNN is a brute-force `vec_distance_cosine` scan with top-k in SQL, no `vec0` index; a Python whose `sqlite3` cannot load extensions is refused by name | the pure-Python scan was about 90% of tier 2 and failed Goal 4 on a busy runner; 265 ms -> 55 ms P95 with no second table to keep in sync (issue #392, PR #409) |
| Tech radar (2026-10-05) | `sqlite-vec` is Trial; supersedes the Assess row above | approved by Todd ("Trial it.", issue #392) |
| Open Questions 1-4 (provisional, 2026-10-05) | merges discarded; rebuild manual with an opt-in cadence; backfill user-started at 10 ingests/s, fetch-only, recorded in place; Ollama `nomic-embed-text` and `llama3.1:8b` | chosen during the build so the code could run; none ratified (issue #425) |
| Retrospective (2026-10-05) | drift filed as issues #410-#425 under issue #342; status stays APPROVED | IMPLEMENTED waits on task-027 (the mbp acceptance run), the drift closing, and the owner's call |
| Background-tab capture (2026-10-16) | the writer opens a background tab only for a URL the daemon vets with its fetch address policy; a refused URL captures as `none`; on by default | one address policy for both capture paths, and the daemon can resolve DNS where the extension cannot (owner ruling on issue #410; revisit issue #525) |
| Diff proposals (2026-10-16) | writers only; the contract text is corrected | a reader cannot apply a diff and has no channel to the writer (issue #416; revisit issue #526) |
| Writer binding (2026-10-16) | bind on the first full hello; `dynomark-daemon rebind` releases it; the extension shows when this browser is served as a reader of a writer bound elsewhere | native messaging connects per profile; a silent permanent bind stopped filing after an extension reinstall (issue #419; revisit issue #527) |
| Extension durable state (2026-10-16) | a rule, not a list: whatever an at-least-once path needs; page text only until the daemon acknowledges the save; extension storage is named in the page-text mitigation | supersedes the closed three-key list in The extension and Data Model (issue #420; revisit issue #528) |
| Retention (2026-10-16) | a corpus entry, its saves and placement go 30 days after its bookmark leaves the tree; archived snapshots go after 30 days unless an undo needs them; batch rows stay; answered requests go | nothing was ever deleted, including captured logged-in text (issue #421; revisit issue #529) |
| Built-but-not-designed behaviours (2026-10-16) | every row of issue #422 accepted, except the duplicated move-feedback rule: the daemon's `feedback_of` is the one rule | the extension's copy decided nothing (issue #422; revisit issue #530) |
| Weakened rules restored (2026-10-16) | locked choice -> a sibling or a new leaf; KNN on the current embedding model only, re-embed on change; flags keyed by folder path; chat marks out-of-corpus URLs in the text; contract v2 carries the park reason, an undo `locked` code and the accepted item's scope; diffs stay folder-only for MVP | each was a stated rule the build met only in part (issue #423; revisit issue #531) |
| Open Questions 1-4 (2026-10-16) | ratified as built (see the provisional row of 2026-10-05) | owner ruling (issue #425; revisit issue #532) |
| Body amendment (2026-10-16) | the body is amended to the shapes of issue #424 on the owner's ruling; this table stays append-only | the contract README had become the spec of record (issue #424) |
| Background-tab guard (2026-10-16) | the capture tab opens blank, gets per-tab block rules for loopback, private, link-local and local-name literals, then navigates; after load its final URL is vetted again and a refused or unanswered vet discards the capture; the daemon's `private_addresses` opt-out is learned by vetting a fixed loopback probe | a one-shot vet of the saved URL let a redirect land the logged-in tab on a private address (issue #534 row T1). Residual: DNS rebinding within one load, and a private hostname reached as an intermediate redirect hop or subresource is still requested (its content is never read); recorded on revisit issue #525 |
| Retention of forgotten profiles (2026-10-16) | a reader profile's tree is forgotten once older than the retention window; an entry is judged by the trees still known, whichever profile its jobs came from | an abandoned or reinstalled profile kept entries forever (issue #534 row T4; revisit issue #529) |
| Rebind and live connections (2026-10-16) | every writer-only request re-checks the store's binding; a connection whose profile was rebound away is answered as a reader | `rebind` runs in another process, and a live old connection stayed a writer beside the new one (issue #534 row T3; revisit issue #527) |

---

## Open Questions

None is open. The questions the approved body carried are answered:

- **Q1 Merge rules for audit** -- answered: merges are discarded and diffs
  are folder adds and moves only for MVP (Key Decisions "Open Questions
  1-4" of 2026-10-05 and 2026-10-16, and "Weakened rules restored",
  2026-10-16).
- **Q2 Rebuild cadence** -- answered: manual, with an opt-in cadence (the
  same Key Decisions rows).
- **Q3 Backfill** -- answered: started by the user, rate-bounded,
  fetch-only, recorded in place and never re-filed (the same Key Decisions
  rows; The daemon, "Backfill").
- **Q4 Default models** -- answered: the local defaults the 2026-10-05 Key
  Decisions row names, ratified 2026-10-16; vendor and model ids stay out
  of this body.
- **Q5 Firefox timing** -- answered: the Firefox adapters are built in MVP,
  as the Key Decisions "Scope" row set out; the sidebar is the chat surface
  there (The extension).

---

## Rejections

- **Per-host `Dynomark.<host>` folders with a `Follow Up` claiming step**
  (the proposal's scheme) -- duplicates the whole hierarchy on every
  device, needs a distributed lock built on a synced move with minutes of
  latency, and still double-files; one writer removes all of it.
- **Localhost HTTP with a pasted bearer token as the default transport** --
  an open port reachable by any local process, a token in extension
  storage, and a manual pairing step; a native-messaging shim over an
  owner-only unix socket has none of these.
- **A per-connection native host as the daemon** -- dies with the browser
  port, so nothing runs while the extension is asleep; the shim forwards to
  a long-lived process instead.
- **Doing capture, extraction or model calls in the extension** -- the
  extension runtime is terminated when idle; long or stateful work belongs
  in the daemon.
- **Snapshot replay as the undo mechanism** -- restores the whole tree and
  loses unrelated edits made since; the guarded inverse does not.
- **An unguarded inverse** -- reverts a node the user has since moved and
  removes a folder others have since filed into; the guard skips both and
  reports them.
- **`activeTab`-only capture** -- the save dialog is not an extension
  gesture, so the permission is never granted on Ctrl+D; capture would
  degrade to fetch and lose logged-in pages.
- **Karakeep or Grimoire as the required backend** -- each is its own
  system of record with a heavy or unsigned install path; neither places
  into a hierarchy. Either may still be tried behind the ports later.
- **Gosuki as the bookmark watcher** -- a second component to install for
  multi-browser reach the design does not need.
- **A text field on the bookmark bar** -- the bar holds only bookmarks and
  folders; the omnibox keyword is the entry point.
- **Three extensions for three live keywords** -- one manifest keyword is
  the platform limit; extra keywords are site-search shortcuts without
  live suggestions (Future Considerations).
- **Corpus store as a bare parameter (no port)** -- the first draft's
  choice; it put a vendor in the application layer and made every use case
  untestable without real I/O, and SEMANTIC-SEARCH already carries the same
  port with two adapters. What stays rejected is a *second production*
  store: SQLite is the only one.
- **A scheduler port** -- the daemon's job loop and rebuild timer have one
  implementation forever; an in-process loop with `RetryPolicy` as a value.
- **"Daemon language" as a seam row** -- a language is not an axis a port
  carries; the versioned contract schema is what makes the daemon
  swappable, recorded as a Key Decision.
- **A rules-first taxonomy engine in v1** (orgmarks' approach) --
  `MoveFeedback` examples fill the same role for a live tool; revisit if
  placement proves unstable (Future Considerations).
- **Overturned from BOOKMARK-ORGANIZER.DESIGN.md, with the reason:**
  *extension form factor* (rejected there for store review and no
  filesystem access; self-installed and paired with a daemon, neither
  applies), *SQLite state between runs* (a live corpus with vectors and a
  write log has no YAML equivalent), *embedding pipeline* (content search
  and grounded chat are goals here, not overhead). The original
  objections were correct for a batch export/import tool and do not
  transfer to a live one.

---

## Future Considerations

- **Phone search and chat** -- a second `TransportPort` adapter over HTTPS
  behind the fleet's Access gate, its own design record.
- **Extra keywords** -- site-search shortcuts to the extension's search
  page, no live suggestions.
- **MCP endpoint** -- so coding agents can query the corpus; a read-only
  adapter over `search_corpus` and `ask`.
- **Dead-link checking and page archival** -- once the corpus is stable.
- **Rules-first placement** -- port orgmarks' taxonomy hints if feedback
  alone does not stabilize placement.
- **Retiring orgmarks** -- a separate decision once Dynomark has run for a
  while on the writer host.

---

## Related Documents

- [BOOKMARK-ORGANIZER.DESIGN.md](./BOOKMARK-ORGANIZER.DESIGN.md) -- the
  offline predecessor; this record supersedes it for the live flow and
  overturns three of its rejections (see Rejections).
- [SEMANTIC-SEARCH.DESIGN.md](./SEMANTIC-SEARCH.DESIGN.md) -- the same
  store, embedding and Ollama port shapes, for terminal logs.
- [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md) -- radar process;
  `lmde/TECH_RADAR.md` holds the rows.
- tds-internal `ops/terraform/` and `docs/policy/` -- the Access gate a
  future phone adapter would sit behind.
