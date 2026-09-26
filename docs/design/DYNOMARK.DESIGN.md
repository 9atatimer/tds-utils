# Dynomark -- live AI filing for native browser bookmarks

> **Status:** DRAFT
> **Date:** 2026-09-26
> **Authors:** Todd + Claude
> **Depends on:** [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md)
> **Origin:** "Dynomark -- Product Proposal" (2026-09-25, PDF, not in repo);
> the review that produced this record is summarized in Key Decisions.

---

## Overview

Bookmarks pile up unfiled and unfindable, and every AI bookmark tool fixes
that by moving the links into its own app. Dynomark keeps the browser's
native bookmark tree as the only interface: the user saves a page into a
`Follow Up` folder with the normal Ctrl+D, a local daemon captures, reads,
summarizes and embeds it, and a thin extension files it into a `Dynomark`
folder the tool maintains. An address-bar keyword gives fuzzy search over
titles and captured content with an LLM chat fallback grounded in the
corpus. Every write to the tree is logged and undoable, and because the
filed tree is plain synced bookmarks, a phone sees it with no software
installed.

---

## Goals

1. **Zero-friction capture** -- saving into `Follow Up` with the native
   bookmark dialog is the entire ingest gesture, from any signed-in device
   including a phone. No extension popup is required to save.
2. **Live filing** -- a `Follow Up` save on the writer host is captured,
   enriched, searchable and filed under `Dynomark` within 60 s of the save
   (P95, daemon running, local models warm), without closing the browser.
3. **Stable structure** -- a bookmark's folder changes only by a new
   placement of a new item, a user move, an explicitly confirmed rebuild, or
   an explicitly accepted audit item. Two runs of placement over the same
   corpus and tree outline propose the same folder for the same item
   (deterministic given the same model output cache).
4. **Fast recall** -- tier-1 (local index) suggestions render within 20 ms
   of a keystroke at 10,000 bookmarks; tier-2 (daemon, hybrid) results
   arrive within 500 ms (P95) and find words that appear only in captured
   page text.
5. **Grounded chat** -- an answer cites corpus entries by identity; a
   citation opens the bookmark in one click. A recommendation from outside
   the corpus is labelled as such.
6. **Undoable, never destructive** -- every write batch the extension
   applies can be reverted by one command, unrelated user edits made since
   are preserved, and nothing is ever hard-deleted by Dynomark: removals
   move to `Graveyard`.
7. **Multi-device sanity** -- exactly one host writes the tree; every other
   host and every phone reads the same filed tree through the browser's own
   sync, and none of them can conflict with the writer.
8. **Ownership boundary** -- the extension writes only under `Follow Up`,
   `Dynomark` and `Graveyard`, except for an audit item the user accepted
   in the diff view. A write outside that set is a defect, and the domain
   refuses to construct it.

---

## Non-Goals

- **A standalone bookmark app or read-it-later reader** -- the native tree
  is the interface; a second place to live is the thing being avoided.
- **Mobile capture or processing** -- mobile browsers run no extension and
  no daemon. A phone saves into `Follow Up` and browses `Dynomark`; that is
  its whole surface in v1.
- **Team or shared collections** -- single user, single sync account.
- **Automatic merging into the user's own bookmark bar** -- audit is
  suggest-only, one accepted item at a time, in v1.
- **Dead-link checking and page archival** -- orthogonal, network-bound;
  deferred (Future Considerations).
- **Replacing orgmarks' batch export/import workflow** -- orgmarks stays as
  it is; Dynomark does not modify it. Whether it is later retired is a
  separate decision.

---

## Architecture Overview

Two runtimes, one ubiquitous language. The extension runtime is short-lived
and holds no durable state; the daemon runtime holds all of it. Dependencies
point inward in both: adapters -> application -> domain.

```
              user: Ctrl+D into "Follow Up"           user on any device,
                          |                            phone included: reads
                          v                            "Dynomark" via sync
  +-------------------------------------------+               ^
  |          browser bookmark tree            |<--------------+
  |  Follow Up | Dynomark | Graveyard | rest  |     browser sync
  +----------+--------------------------------+
             | onCreated/onMoved         ^ create/move/remove
             v                           |
  +----------+---------------------------+----+
  |  EXTENSION RUNTIME (composition root 1)   |
  |  adapters: BookmarkTreePort (browser),    |
  |            ContentSourcePort (open tab),  |
  |            TransportPort (native msg)     |
  |  app:      search_local, apply_batch      |
  |  domain:   ranking, batch/inverse ops     |
  +----------------+--------------------------+
                   | TransportPort (request/response + push)
                   v
  +----------------+--------------------------+
  |  DAEMON RUNTIME (composition root 2)      |
  |  app:      ingest, process, place, ask,   |
  |            search_corpus, undo, audit ... |
  |  domain:   Bookmark, Placement, Corpus,   |
  |            WriteBatch, AuditDiff rules    |
  |  adapters: EmbeddingPort, CompletionPort, |
  |            ContentSourcePort (fetch),     |
  |            corpus store (SQLite, param)   |
  +----------------+--------------------------+
                   |
        +----------+-----------+
        v                      v
  local or cloud         corpus store on disk
  embedding/LLM          (content, vectors, log,
  (model id at edge)      snapshots, feedback)
```

**Core (stable, in the problem's language):** the bookmark tree and the
ownership boundary; placement and its reasons; the write batch and its
inverse; ranking; the audit diff. None of these know a browser API, a wire
format, a vendor, a model id, or a database.

**Edges (volatile, one seam each):** see the seam table under Design.

---

## Design

### Ubiquitous language

| Term | Meaning |
|---|---|
| `Bookmark` | A URL plus title at a `FolderPath` in the tree, with a per-profile `NodeId` and a cross-host `Identity` (normalized URL) |
| `FolderPath` | Ordered folder names from a root; `Dynomark/...` paths are the ones Dynomark owns |
| `Tree outline` | The folder skeleton of the owned subtree, with pin/lock flags and per-folder item counts; no URLs |
| `Capture` | Page content for a bookmark: readable text, title, fetched-at, source (tab or fetch) |
| `CorpusEntry` | A bookmark plus its capture, summary, tags and embedding; the unit of search and retrieval |
| `Placement` | The folder chosen for an entry plus a `PlacementReason` (neighbours consulted, rationale, feedback used) |
| `MoveFeedback` | A user-made move inside `Dynomark`, recorded as a labelled example for future placements |
| `WriteBatch` | An ordered list of `Operation`s (create folder, create, move, remove-to-graveyard) the extension applies atomically from the user's point of view, with its inverse |
| `Snapshot` | A full tree capture taken before a batch; the fallback export, not the undo mechanism |
| `Job` | The durable unit of daemon work for one entry; see State Machine |
| `Query` / `Hit` | A search string and a ranked match with its source tier |
| `Question` / `Answer` / `Citation` | A chat turn, its grounded reply, and a reference to a `CorpusEntry` |
| `AuditDiff` / `AuditItem` | A proposed set of adds/moves/merges between `Dynomark` and the user's own bar, and one accepted line of it |
| `Host` | A machine running a daemon; exactly one holds the `writer` role |

### Seams (axes of change)

| Axis of change | Seam | Implementations (now / plausible) |
|---|---|---|
| Browser (Chrome now, Firefox later) | `BookmarkTreePort` | Chrome extension adapter / Firefox extension adapter |
| Extension <-> daemon transport | `TransportPort` | native messaging / HTTPS behind the Access gate for a phone client |
| Where page content comes from | `ContentSourcePort` | open-tab snapshot in the extension / daemon-side fetch |
| Embedding vendor and model | `EmbeddingPort`, model id supplied at the edge | local (Ollama) / cloud |
| Completion vendor and model | `CompletionPort`, model id supplied at the edge | local (Ollama) / Anthropic / OpenAI |
| Daemon implementation language | the transport contract itself | any process that speaks the contract is the daemon |

The corpus store (SQLite with FTS5 and a vector extension) is a parameter,
not a port: one implementation, no vendor boundary crossed. See Rejections.

### The extension

| Responsibility | Details |
|---|---|
| Watch `Follow Up` | On a create or move into `Follow Up`, hand the bookmark to the daemon as an ingest request. The folder is resolved by name at startup and re-resolved if it disappears. |
| Capture from the open tab | If a tab shows the saved URL, read its title and readable text and attach it to the ingest request. This is the only moment content is read from a page; it needs the browser's all-sites host permission (Key Decisions). If no tab matches, the request carries no capture and the daemon fetches. |
| Apply write batches | Receive a `WriteBatch`, apply its operations in order through `BookmarkTreePort`, and acknowledge with the resulting `NodeId`s. A batch that would touch a path outside the owned set, or outside an accepted audit item, is rejected before the first operation. |
| Record feedback | A user move inside `Dynomark` (an `onMoved` whose source and destination are both owned and which the extension did not itself perform) is sent as `MoveFeedback`. |
| Tier-1 search | Hold a compact local index (identity, title, path, tags, one-line summary) pulled from the daemon on change; rank per keystroke with a fuzzy score, a frecency boost from browser history, and a small bonus for owned items. No transport call on this path. |
| Tier-2 search | When tier-1 returns fewer than N hits or weak scores, ask the daemon (debounced) and append its hits below tier-1. |
| Ask fall-through | The last suggestion is always `Ask: <query>`; entering it, or entering with no hit, opens the chat surface with the query pre-sent. |
| Chat surface | An extension page in a popup window (tab fallback), showing `Answer`s with clickable `Citation`s, "file this", and "why here". Conversation state lives in the window and is not persisted. |
| Settings | Daemon transport selection, writer flag display, `Follow Up` behaviour. Stored in extension-local storage; nothing secret. |

The extension holds no durable state beyond settings and the rebuildable
tier-1 index. Every operation it performs is short and idempotent, because
its runtime can be terminated between any two events. Results the daemon
produced while the extension was not running are held by the daemon and
delivered on the next connect (transport contract below).

### The daemon

| Responsibility | Details |
|---|---|
| Durable jobs | One `Job` per ingested entry, persisted before acknowledgement, retried with backoff on a retryable failure; a job that exhausts retries is `FAILED` and the bookmark stays in `Follow Up`, untouched. |
| Extract and enrich | Turn a capture into readable text; produce summary, tags and embedding through the ports. |
| Index | Full-text over captured text and titles; vector similarity over embeddings; hybrid ranking for tier-2 and retrieval. |
| Place | Given an entry, its nearest placed neighbours, the tree outline and recent `MoveFeedback`, choose an existing owned folder or propose exactly one new leaf, and record the `PlacementReason`. Pinned or locked folders are never moved, renamed or merged. |
| Write log | Every `WriteBatch` is recorded with its inverse before it is handed to the extension, and marked applied only on acknowledgement. A `Snapshot` is stored before each batch. |
| Undo | Invert the operations of one applied batch, in reverse order, skipping (and reporting) any operation whose target node no longer exists; a removal is undone by moving the node back out of `Graveyard`. |
| Audit | On command, propose an `AuditDiff` between `Dynomark` and the user's own bar. Nothing is applied until the user accepts one `AuditItem`; each acceptance is its own `WriteBatch`. |
| Rebuild | On command or a configured slow schedule, propose a reorganized owned tree as a diff; apply only on confirmation, as ordinary batches. |
| Chat | Retrieve top-k entries for a `Question`, answer through `CompletionPort` with `Citation`s, and mark any URL not in the corpus as external. |
| Writer role | A configuration value. A daemon without it ingests and indexes for its own search and chat but produces no `WriteBatch` and answers "not the writer" to any write-producing command. |

### Transport contract (the load-bearing part only)

| Guarantee | Statement |
|---|---|
| Identity and version | The first exchange on a connection states a contract version on both sides. A mismatch stops all write-producing flows; search and chat may continue if the reader side is newer. |
| Direction | Extension -> daemon: requests with a caller-chosen request id. Daemon -> extension: responses by id, plus unsolicited events (job finished, batch ready). |
| Delivery | Requests are at-least-once from the extension's side; ingest is idempotent on (`NodeId`, `Identity`). Events are durable on the daemon until acknowledged; on connect the extension asks for everything unacknowledged. |
| Partial failure | A `WriteBatch` is `PROPOSED` until the extension acknowledges it `APPLIED` with node ids or `REJECTED` with a reason. Unacknowledged batches are re-offered on the next connect, never applied twice (the extension checks the batch id). |
| Retryable errors | Transport loss and daemon restart are retryable by reconnecting. A `REJECTED` batch is not retried automatically; it surfaces in chat and the audit view. |
| Confidentiality | The transport never leaves the machine in v1. A remote adapter (phone client) is a separate design record; it must sit behind the fleet's Access gate. |

Message names, field shapes and serializers are the implementation's
business and are not pinned here.

### Placement policy (the rule, once)

1. Nearest neighbours by embedding among already-placed entries.
2. The completion port chooses an existing owned folder path, or proposes
   one new leaf under an existing owned folder, given: the neighbours and
   their folders, the tree outline, and the most recent `MoveFeedback`
   examples.
3. A proposed leaf that collides with an existing folder name at the same
   level resolves to the existing folder.
4. The result and its reason are recorded before the batch is built.

Placement is incremental; it never moves an existing item. Only a confirmed
rebuild or an accepted audit item moves what is already filed.

### Multi-device policy

| Folder | Who writes | Who reads |
|---|---|---|
| `Follow Up` | any device adds (phone included); the writer host moves items out | writer host |
| `Dynomark` | the writer host only | every device, through sync |
| `Graveyard` | the writer host only | every device |
| rest of the tree | the user; the writer host only inside an accepted `AuditItem` | every device |

There is no claiming step and no cross-host de-duplication, because there
is one writer. A non-writer daemon may still index the synced tree for its
own search and chat. Changing the writer is a configuration change on two
hosts; the design does not arbitrate two hosts both configured as writer
(Open Questions).

### Module map (phase 3)

| Layer | Extension runtime | Daemon runtime |
|---|---|---|
| Domain | tree model, ownership boundary check, batch/inverse operations, fuzzy+frecency ranking | tree model (shared language), placement rule, hybrid ranking, audit diff, batch/inverse operations |
| Application (use cases) | `search_local`, `apply_batch`, `record_move` | `ingest`, `process_job`, `place`, `search_corpus`, `ask`, `undo`, `propose_audit`, `accept_audit_item`, `explain_placement`, `build_local_index` |
| Ports | `BookmarkTreePort`, `ContentSourcePort`, `TransportPort` | `TransportPort`, `ContentSourcePort`, `EmbeddingPort`, `CompletionPort` |
| Composition root | the extension's background entry point wires browser adapters and the transport adapter | the daemon's main wires the transport, model and content adapters and the store parameter |

The domain is expressed twice because the runtimes cannot share a process;
the language is one, and each side tests its domain in isolation.

---

## Behaviors and Interfaces

Signatures are language-neutral; inputs and outputs are the nouns above.
Ports arrive as keyword dependencies after the values.

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| A save is ingested | `ingest(bookmark: Bookmark, capture: Capture or none) -> Job` | none (store is a parameter) | Given a bookmark newly in `Follow Up`, When ingested, Then a `Job` exists in `QUEUED` and a second identical ingest returns the same job |
| Content is captured from the open tab | `capture(bookmark: Bookmark, *, content: ContentSourcePort) -> Capture` | `ContentSourcePort` | Given a tab showing the URL, When captured, Then the capture's source is `tab` and its text is non-empty |
| Content falls back to fetch | (same use case; no matching tab) | `ContentSourcePort` | Given no tab shows the URL, When captured, Then the source is `fetch`; if the fetch fails, the capture has title and URL only and the job continues |
| A job is processed to an entry | `process_job(job: Job, *, embedding: EmbeddingPort, completion: CompletionPort) -> CorpusEntry` | `EmbeddingPort`, `CompletionPort` | Given a job with a capture, When processed, Then the entry has summary, tags and embedding and is findable by a word that appears only in the captured text |
| A failed enrichment is retried, then parked | (same use case; error path) | as above | Given a completion that errors N times, When processed, Then the job is `FAILED`, the bookmark is still in `Follow Up`, and nothing was written to the tree |
| An entry is placed | `place(entry: CorpusEntry, outline: TreeOutline, feedback: list[MoveFeedback], *, embedding: EmbeddingPort, completion: CompletionPort) -> Placement` | `EmbeddingPort`, `CompletionPort` | Given three placed neighbours in one folder, When placed, Then the placement names that folder and its reason lists the neighbours |
| Placement respects a lock | (same use case) | as above | Given the chosen folder is locked, When placed, Then the placement is a sibling or new leaf, never inside the locked folder |
| A batch is applied | `apply_batch(batch: WriteBatch, *, tree: BookmarkTreePort) -> BatchReceipt` | `BookmarkTreePort` | Given a batch of create+move under `Dynomark`, When applied, Then every operation is performed in order and the receipt maps each operation to a node id |
| A batch outside the boundary is refused | (same use case; error path) | `BookmarkTreePort` | Given a batch containing a move to a path not owned and not covered by an accepted audit item, When applied, Then no operation runs and the receipt is `REJECTED` |
| A user move becomes feedback | `record_move(move: Move) -> MoveFeedback or none` | none | Given an `onMoved` between two owned folders not caused by Dynomark, When recorded, Then a `MoveFeedback` exists; a move Dynomark itself made yields none |
| Tier-1 search | `search_local(query: Query, index: LocalIndex, frecency: Frecency) -> list[Hit]` | none | Given an index of 10,000 entries, When queried, Then hits are ranked with title matches first and return within the tier-1 budget |
| Tier-2 search | `search_corpus(query: Query, *, embedding: EmbeddingPort) -> list[Hit]` | `EmbeddingPort` | Given a word only in captured text, When queried, Then the entry is a hit with source `corpus` |
| A question is answered with citations | `ask(question: Question, history: list[Turn], *, embedding: EmbeddingPort, completion: CompletionPort) -> Answer` | `EmbeddingPort`, `CompletionPort` | Given a question the corpus can answer, When asked, Then the answer carries at least one `Citation` to a `CorpusEntry` |
| An out-of-corpus recommendation is marked | (same use case) | as above | Given the completion returns a URL not in the corpus, When asked, Then the answer marks it `external` |
| A batch is undone | `undo(batch_id: BatchId, *, tree: BookmarkTreePort) -> BatchReceipt` | `BookmarkTreePort` | Given an applied batch and an unrelated user edit made afterwards, When undone, Then the batch's operations are reverted in reverse order and the unrelated edit remains |
| Undo tolerates a vanished node | (same use case; error path) | `BookmarkTreePort` | Given one operation's node was deleted by the user, When undone, Then that operation is skipped and reported and the rest are reverted |
| An audit is proposed | `propose_audit(outline: TreeOutline, own_bar: TreeOutline, *, completion: CompletionPort) -> AuditDiff` | `CompletionPort` | Given `Dynomark` and the user's bar, When proposed, Then the diff lists adds, moves and merges and applies nothing |
| One audit item is accepted | `accept_audit_item(item: AuditItem) -> WriteBatch` | none | Given an accepted item that targets the user's bar, When accepted, Then a batch is produced whose boundary exception is exactly that item, and it is undoable like any batch |
| A placement is explained | `explain_placement(identity: Identity) -> PlacementReason` | none | Given a filed entry, When explained, Then the reason names the folder, the neighbours and the feedback used |
| The local index is built | `build_local_index() -> LocalIndex` | none | Given the corpus, When built, Then the index holds identity, title, path, tags and one-line summary per entry and nothing larger |
| A non-writer refuses to write | `place`, `accept_audit_item`, `undo` on a host without the writer role | none | Given the writer flag is off, When any write-producing use case runs, Then it returns `NotWriter` and no batch is produced |

---

## State Machine

The `Job` is the lifecycle-bearing entity.

```
 +--------+   +-----------+   +-----------+   +----------+   +--------+   +-------+
 | QUEUED |-->| CAPTURING |-->| EXTRACTED |-->| ENRICHED |-->| PLACED |-->| FILED |
 +--------+   +-----------+   +-----------+   +----------+   +--------+   +-------+
      |             |               |               |              |
      +------+------+---------------+---------------+--------------+
             v  (retries exhausted, or batch REJECTED)
         +--------+
         | FAILED |
         +--------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| QUEUED | CAPTURING | job picked up | writer or reader host alike |
| CAPTURING | EXTRACTED | capture present (tab or fetch) or fetch gave up | a title-only capture still advances |
| EXTRACTED | ENRICHED | summary, tags, embedding produced | ports returned |
| ENRICHED | PLACED | placement recorded | host holds the writer role; otherwise the job rests at ENRICHED as searchable-only |
| PLACED | FILED | batch acknowledged `APPLIED` | extension receipt |
| any | FAILED | retryable error after N attempts, or batch `REJECTED` | bookmark remains in `Follow Up`, untouched |
| FAILED | QUEUED | user retries from chat or menu | always allowed |

A batch has its own three states, `PROPOSED -> APPLIED | REJECTED`, given in
the transport contract.

---

## Data Model

Logical model; the physical schema is the implementation's business.

```
bookmark
+-- identity          normalized URL (cross-host identity)
+-- node_id           per-profile browser node id (this host)
+-- title, url, folder_path, date_added

capture
+-- identity          FK bookmark
+-- source            tab | fetch | none
+-- text, fetched_at

entry
+-- identity          FK bookmark
+-- summary, tags[]
+-- embedding         vector (model id recorded alongside)
+-- indexed_at

placement
+-- identity, folder_path, reason (neighbours, rationale, feedback ids), model id, created_at

owned_folder
+-- stable_id, folder_path, node_id (this host), pinned, locked

move_feedback
+-- identity, from_path, to_path, observed_at

job
+-- job_id, identity, state, attempts, last_error, updated_at

write_batch
+-- batch_id, operations[], inverse[], state (PROPOSED|APPLIED|REJECTED), snapshot_id, audit_item_id or none

snapshot
+-- snapshot_id, taken_at, tree (full JSON)
```

Constraints: one `entry` per `identity`; `write_batch.operations` all target
owned paths unless `audit_item_id` is set and each operation is inside that
item; `owned_folder.stable_id` never changes once assigned.

---

## Data Warehouse

Nothing is ledgered. Dynomark is a single-user, laptop-resident tool; its
write log and snapshots are product state kept for undo, live only in the
local corpus store, and are not exported to any fleet ledger.

---

## Security Considerations

- **All-sites host permission** -- required so the extension can read the
  DOM of the tab that shows a just-saved page (logged-in and paywalled
  content). Mitigation: the extension is self-installed and unpacked, not
  store-listed; content is read only in response to a save into
  `Follow Up`, never on navigation; non-http(s) URLs are never captured.
- **Page content of logged-in sessions on disk** -- the corpus store holds
  captured text. Mitigation: the store lives in the user's state directory
  with owner-only permissions, is never synced or backed up by Dynomark, and
  is excluded from any repo.
- **Cloud model egress** -- summaries and questions may leave the machine.
  Mitigation: model choice is per install and per port, local is the
  default, and the setting is shown in the chat surface.
- **Transport exposure** -- native messaging binds the daemon to the
  extension's identity in the host manifest and opens no port. A future
  remote adapter is a separate record and sits behind the Access gate.
- **Tree damage** -- the ownership boundary is enforced in the domain
  before any operation runs; every batch has a recorded inverse and a
  preceding snapshot; removals go to `Graveyard`.
- **Daemon-side fetch** -- carries no cookies and follows the same
  non-http(s) exclusion; it cannot reach content the machine's network
  cannot.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Source of truth | the native browser bookmark tree | no new app to live in; sync to every device, phone included, comes free |
| Process split | thin extension owns tree writes; daemon owns capture, corpus, models | the extension runtime cannot run long jobs or hold state; the daemon can |
| Multi-device | one shared `Dynomark` folder, one configured writer host | per-host folders duplicate the hierarchy on every device and force a claiming protocol; one writer needs neither |
| Phone | a consumer: saves into `Follow Up`, reads `Dynomark` via sync | mobile browsers run no extension; this gives capture and browse with zero mobile software |
| Corpus locality | one corpus per daemon; only the writer files | local search and chat on every laptop without a corpus sync problem |
| Transport | `TransportPort`; native messaging first | no open port, no pasted token, browser launches the daemon; a phone adapter is a second implementation |
| Daemon identity | the transport contract, not a language | any implementation that speaks it is the daemon; hot-swappable |
| Content capture | all-sites host permission, daemon fetch as fallback | the only way to capture logged-in pages at save time |
| Undo | inverse of a recorded operation log per batch | snapshot replay cannot preserve unrelated later edits; an inverse can |
| Placement | incremental, embedding neighbours + completion + feedback; rebuild only on confirmation | stability over cleverness; a tree that reshuffles is not trusted |
| Deletions | `Graveyard`, emptied by hand only | no hard delete path exists to get wrong |
| Audit / merge | command-triggered, diffed, one accepted item at a time | keeps the user's own bar under the user's control while rules are learned |
| Embedding and completion vendors | `EmbeddingPort`, `CompletionPort`; model ids at the edge | local by default, cloud by choice, no vendor in the core |
| Corpus store | a parameter (SQLite + FTS5 + vector extension), not a port | one implementation, no vendor boundary crossed |
| Relation to orgmarks | supersedes it for the live flow; orgmarks is untouched | orgmarks required off-lining the browser and went unused; this record overturns its rejections that only held for a batch tool (see Rejections) |
| Tech radar | `sqlite-vec` is Assess on `lmde/TECH_RADAR.md`; propose Trial with this record | first production use in the fleet; SEMANTIC-SEARCH already names it |

---

## Open Questions

1. **`Follow Up` semantics after filing** -- consume the item, or keep it as
   a to-do with states (new, processed, read, done) and resurfacing?
2. **Two hosts configured as writer** -- refuse on detection (a marker in
   the owned tree names the writer), or last-configured wins?
3. **Merge rules for audit** -- undefined for v1 by intent; learned from use.
4. **Rebuild cadence** -- manual only, or a slow default schedule?
5. **Backfill** -- run the existing tree through capture and indexing at
   first install (searchable, not re-filed), and at what rate?
6. **Default models** -- which local embedding and completion models are the
   shipped defaults.
7. **Firefox timing** -- after which phase the second `BookmarkTreePort`
   adapter is worth building.

---

## Rejections

- **Per-host `Dynomark.<host>` folders with a `Follow Up` claiming step**
  (the proposal's scheme) -- duplicates the whole hierarchy on every
  device, needs a distributed lock built on a synced move with minutes of
  latency, and still double-files; one writer removes all of it.
- **Localhost HTTP with a pasted bearer token as the default transport** --
  an open port reachable by any local process, a token in extension
  storage, and a manual pairing step; native messaging has none of these.
- **Doing capture, extraction or model calls in the extension** -- the
  extension runtime is terminated when idle; long or stateful work belongs
  in the daemon.
- **Snapshot replay as the undo mechanism** -- restores the whole tree and
  loses unrelated edits made since; the inverse of the batch's own
  operations does not.
- **`activeTab`-only capture** -- the save dialog is not an extension
  gesture, so the permission is never granted on Ctrl+D; capture would
  degrade to daemon fetch and lose logged-in pages.
- **Karakeep or Grimoire as the required backend** -- each is its own
  system of record with a heavy or unsigned install path; neither places
  into a hierarchy. Either may still be tried behind the ports later.
- **Gosuki as the bookmark watcher** -- a second component to install for
  multi-browser reach the design does not need; the extension already
  sees every tree event.
- **A text field on the bookmark bar** -- the bar holds only bookmarks and
  folders; the omnibox keyword is the entry point.
- **Three extensions for three live keywords** -- one manifest keyword is
  the platform limit; extra keywords are site-search shortcuts without
  live suggestions (Future Considerations).
- **A `CorpusStorePort`** -- single implementation forever in this design;
  a port would be ceremony.
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
- **Firefox** -- a second `BookmarkTreePort` adapter; the sidebar is the
  natural chat surface there.
- **Extra keywords** -- site-search shortcuts to the extension's search
  page, no live suggestions.
- **MCP endpoint** -- so coding agents can query the corpus; a read-only
  adapter over the same use cases.
- **Dead-link checking and page archival** -- orthogonal, network-bound;
  once the corpus is stable.
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
  embedding, sqlite-vec and Ollama port shapes, for terminal logs.
- [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md) -- radar process;
  `lmde/TECH_RADAR.md` holds the rows.
- tds-internal `ops/terraform/` and `docs/policy/` -- the Access gate a
  future phone adapter would sit behind.
