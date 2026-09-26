# Dynomark -- live AI filing for native browser bookmarks

> **Status:** DRAFT
> **Date:** 2026-09-26
> **Authors:** Todd + Claude
> **Depends on:** [WIP.TECH_RADAR.DESIGN.md](./WIP.TECH_RADAR.DESIGN.md)
> **Origin:** "Dynomark -- Product Proposal" (2026-09-25, PDF, not in repo);
> the review that produced this record is summarized in Key Decisions.
> **As-built:** `docs/arch/` does not exist in this repo yet; the only
> shipped related component is orgmarks (`bookmark-organizer/`).

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

1. **Zero-friction capture** -- saving into `Follow Up` with the native
   bookmark dialog is the entire ingest gesture, from any signed-in device
   including a phone. No extension popup is required to save.
2. **Live filing** -- on the writer host, the interval from the daemon
   receiving an ingest request to the extension's `APPLIED` receipt for
   that entry is under 60 s at P95 (daemon up, local models warm), and the
   browser is never closed for it.
3. **Stable structure** -- a filed bookmark's folder changes only by a user
   move, an accepted `DiffItem`, or an undo. `place` is a pure function of
   (entry, neighbours, outline, feedback, completion output): with a fake
   `CompletionPort` returning a fixed answer, two calls give one placement.
4. **Fast recall** -- tier-1 suggestions render within 20 ms (P95) of a
   keystroke at 10,000 entries; tier-2 hits arrive within 500 ms (P95) and
   include an entry whose only match is in captured page text.
5. **Grounded chat** -- an `Answer` cites `CorpusEntry` identities that the
   retrieval step returned; an identity the completion invents is dropped;
   a URL outside the corpus is marked `external`.
6. **Undoable, never destructive** -- every `APPLIED` batch has an inverse
   that reverts each of its operations whose node is still where the batch
   left it, skips and reports the rest, and never hard-deletes: a removal
   is a move to `Graveyard`.
7. **One writer** -- no host other than the one whose `HostRole` is
   `writer` produces a `WriteBatch`; a `Follow Up` save is filed by exactly
   one host; edits arriving from other devices are user edits.
8. **Ownership boundary** -- a `WriteBatch` whose operations target a path
   outside `OwnedRoots`, unless every such operation lies inside one
   accepted `DiffItem`, cannot be constructed: `file` and `accept_diff_item`
   raise before a batch exists.

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
- **Arbitrating two hosts both configured as writer** -- configuration
  error, detected and reported (Open Questions), not resolved.

---

## Architecture Overview

Two runtimes, one ubiquitous language. The extension runtime is short-lived
and holds only settings, a rebuildable index and an in-flight batch cursor;
the daemon runtime holds everything durable. Dependencies point inward in
both: adapters -> application -> domain.

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
  |  adapters: BookmarkTreePort, HistoryPort, |
  |            ContentSourcePort (open tab),  |
  |            TransportPort (native msg)     |
  |  app:      submit_save, search_local,     |
  |            search_remote, sync_index,     |
  |            apply_batch, ack_batch,        |
  |            record_move                    |
  |  domain:   ranking, boundary, batch ops   |
  +----------------+--------------------------+
                   | TransportPort: native-messaging shim -> unix socket
                   v
  +----------------+--------------------------+
  |  DAEMON RUNTIME (composition root 2)      |
  |  app:      ingest, capture, process_job,  |
  |            place, file, undo, ask,        |
  |            search_corpus, propose_diff,   |
  |            accept_diff_item, ...          |
  |  domain:   Bookmark, Placement, WriteBatch|
  |            + inverse, TreeDiff, ranking   |
  |  adapters: CorpusStorePort (SQLite),      |
  |            EmbeddingPort, CompletionPort, |
  |            ContentSourcePort (fetch)      |
  +----------------+--------------------------+
                   |
        +----------+-----------+
        v                      v
  local or cloud         corpus store on disk
  embedding/LLM          (entries, vectors, jobs,
  (model id at edge)      batches, snapshots, feedback)
```

**Core (stable, in the problem's language):** the tree and `OwnedRoots`;
`Placement` and its reason; `WriteBatch` and its inverse; ranking and
fusion; `TreeDiff`. None of these know a browser API, a wire format, a
vendor, a model id, or a database.

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
| `pinned` | A folder immune to `rebuild` and `audit` moves; still a placement candidate |
| `locked` | A folder excluded from placement candidates and never moved, renamed or merged by any batch |
| `Capture` | Readable text plus title for a bookmark, with `source` in {`tab`, `fetch`, `none`}; extraction to readable text is the content adapter's job |
| `CorpusEntry` | A bookmark plus capture, summary, tags and embedding; the unit of search and retrieval |
| `Placement` | The folder chosen for an entry plus a `PlacementReason` (neighbours, rationale, feedback ids, model id) |
| `Move` | An observed tree move with `origin` in {`extension`, `user`}; the extension adapter sets `origin` from the batch operations it itself issued |
| `MoveFeedback` | A `Move` of origin `user` between two owned folders, recorded on the writer host as a labelled example |
| `Operation` | One of create-folder-at-path, create-at-path, move-to-path, remove-to-graveyard; each is path-idempotent (create if absent, move if not already there) |
| `WriteBatch` | Ordered `Operation`s plus their inverse, a `BatchId`, and an optional accepted `DiffItem` reference |
| `BatchReceipt` | The extension's answer for a batch: `APPLIED` with node ids per operation, `PARTIAL` with the applied prefix, or `REJECTED` with a reason; carries the pre-batch `Snapshot` |
| `Snapshot` | The full tree as the extension read it immediately before applying a batch; the fallback export, not the undo mechanism |
| `Job` | The durable unit of daemon work for one ingested save; see State Machine |
| `RetryPolicy` | Attempts and backoff for retryable job errors; a parameter of the daemon `Config` |
| `HostRole` | `writer` or `reader`; a value from the daemon `Config`, passed to every write-producing use case |
| `NotWriter` | The non-retryable result a write-producing use case returns when `HostRole` is `reader` |
| `Query` / `Hit` | A search string; a ranked match with `tier` in {`local`, `corpus`} and a score |
| `LocalIndex` | Per entry: identity, title, path, tags, one-line summary; at most 512 bytes per entry; pulled from the daemon, held by the extension |
| `Frecency` | A map identity -> visit boost derived from browser history through `HistoryPort` |
| `Turn` / `Question` / `Answer` / `Citation` | One chat exchange; the user's text; the grounded reply; a reference to a `CorpusEntry` identity |
| `RequestId` | The caller-chosen id of one transport request; the delivery guarantee keys on it |
| `DiffKind` | `audit` or `rebuild` |
| `TreeDiff` / `DiffItem` | A proposed set of adds, moves and merges with `kind` in {`audit`, `rebuild`}; one line of it. An item is *accepted* when `accepted_at` is recorded |
| `Config` | The daemon's settings: `HostRole`, model ids, store path, `RetryPolicy`, rebuild cadence. The extension owns only transport selection and `Follow Up` behaviour |

### Seams (axes of change)

| Axis of change | Seam | Implementations (now / plausible) |
|---|---|---|
| Browser tree API (Chrome, Firefox) | `BookmarkTreePort` | Chrome adapter / Firefox adapter |
| Browser history (frecency source) | `HistoryPort` | Chrome adapter / Firefox adapter |
| Extension <-> daemon transport | `TransportPort` | native-messaging shim over a unix socket / HTTPS behind the Access gate for a phone client |
| Where page content comes from | `ContentSourcePort` | open-tab extractor (extension) / fetch-and-extract (daemon); a fallback chain, not a swap |
| Corpus store | `CorpusStorePort` | SQLite with FTS5 and a vector extension (production) / in-memory fake (tests) |
| Embedding vendor and model | `EmbeddingPort`, model id at the edge | local (Ollama) / cloud |
| Completion vendor and model | `CompletionPort`, model id at the edge | local (Ollama) / Anthropic / OpenAI |

The daemon's implementation language is not a seam; it is free because the
transport contract is a versioned schema artifact in the repo that both
runtimes' adapters are generated from or validated against (Key Decisions).

### The extension

| Responsibility | Details |
|---|---|
| Watch `Follow Up` | On a create or move into `Follow Up`, run `capture` with the tab adapter and `submit_save`. Zero folders named `Follow Up` at startup: create one under the bookmarks bar. More than one: use the one under the bookmarks bar and report the others. |
| Capture from the open tab | If a tab shows the saved URL, the tab adapter returns readable text with `source` `tab`. This is the only moment content is read from a page; it needs the browser's all-sites host permission (Key Decisions). Otherwise the request carries `source` `none`. |
| Apply write batches | `apply_batch`: read a `Snapshot`, apply operations in order through `BookmarkTreePort`, recording the applied operation index in extension storage after each; return a `BatchReceipt`. A batch already fully applied (by cursor or by batch id) is answered `APPLIED` again without touching the tree. |
| Record feedback | `record_move` on every `onMoved` whose source and destination are owned; only a `Move` of origin `user` on the writer host becomes feedback (the daemon discards the rest by `HostRole`). |
| Tier-1 search | `search_local` over the `LocalIndex` and `Frecency`. Title matches form a hard tier above path, tag and summary matches; within a tier, fuzzy score then frecency. No transport call. |
| Tier-2 search | `search_remote` when tier-1 returns fewer than `tier2_min_hits` hits or the best score is under `tier2_min_score` (named parameters, values in code); hits append below tier-1. |
| Ask fall-through | The last suggestion is always `Ask: <query>`; entering it, or entering with no hit, opens the chat surface with the query pre-sent. |
| Chat surface | An extension page. It is a view, not a composition root: it sends `Question`s to the background context and renders `Answer`s, `Citation`s, "file this" and "why here". Conversation state lives in the page. |
| Settings | Transport selection and `Follow Up` behaviour, in extension-local storage; nothing secret. |

Every extension operation is short and path-idempotent, because its
runtime can be terminated between any two events. Durable extension state
is exactly: settings, the rebuildable `LocalIndex`, and the in-flight
batch cursor (batch id plus applied operation index).

### The daemon

| Responsibility | Details |
|---|---|
| Process lifetime | The daemon is long-lived and reached over a unix socket with owner-only permissions; the native-messaging host is a shim that forwards one browser connection to it. Jobs run whether or not an extension is connected. |
| Durable jobs | One `Job` per (`NodeId`, `Identity`), persisted before acknowledgement; retried per `RetryPolicy` on a retryable error; `NotWriter` is not retryable and not counted. |
| Capture fallback | `capture` with the fetch adapter, only when the request's capture has `source` `none`; carries no cookies; skips non-http(s) URLs. |
| Enrich and index | Summary, tags and embedding through the ports; full-text and vector indexing through `CorpusStorePort`. Hybrid fusion runs in the domain over the two candidate lists the store returns. |
| Place and file | `place` chooses a folder and records the reason; `file` turns the placement into a `WriteBatch` (with inverse) that the boundary policy has admitted, stores it `PROPOSED`, and offers it to the extension. |
| Duplicate identity | An ingest whose `Identity` already has a `FILED` entry files nothing new: the new node is moved to `Graveyard` by a batch whose reason names the existing placement. |
| Receipts | `APPLIED`: store node ids and the snapshot, job `FILED`. `PARTIAL`: store the snapshot, offer the inverse of the applied prefix as a new batch, job `FAILED`. `REJECTED`: job `FAILED`. |
| Undo | `undo` returns the inverse `WriteBatch` of an `APPLIED` batch, guarded: an inverse operation is kept only if its node is still at the path the batch left it, and a folder removal only if the folder is empty; the rest are dropped and listed in the batch's report. The inverse carries the same `DiffItem` reference if the original had one. |
| Diffs | `propose_diff` of kind `audit` (between `Dynomark` and the user's bar) or `rebuild` (a reorganized owned tree). Nothing is applied until a `DiffItem` is accepted; each acceptance is its own batch. |
| Chat | Retrieve top-k entries, answer through `CompletionPort`, keep only citations the retrieval returned, mark other URLs `external`. |
| Config | Loaded once by the composition root as a `Config` value; `HostRole` is passed into use cases, never read from a global. |

### Transport contract (the load-bearing part only)

| Guarantee | Statement |
|---|---|
| Identity and version | The first exchange on a connection states a contract version on both sides. On mismatch, write-producing flows stop; search and chat continue only if the extension's version is newer than the daemon's. The contract is a versioned schema artifact in the repo. |
| Direction | Extension -> daemon: requests with a caller-chosen request id. Daemon -> extension: responses by id, plus unsolicited events (job finished, batch ready). |
| Delivery | Requests are at-least-once from the extension; ingest is idempotent on (`NodeId`, `Identity`). Events are durable on the daemon until acknowledged; on connect the extension asks for everything unacknowledged. |
| Partial failure | A batch is `PROPOSED` until a `BatchReceipt` arrives. An unacknowledged batch is re-offered on the next connect; the extension answers from its cursor without re-applying. |
| Retryable errors | Transport loss and daemon restart are retryable by reconnecting. `REJECTED` and `PARTIAL` are not retried automatically; they surface in chat and the diff view. |
| Confidentiality | The transport never leaves the machine in v1. A remote adapter is a separate record and sits behind the fleet's Access gate. |

Message names, field shapes and serializers are the implementation's
business and are not pinned here.

### Placement policy (the rule, once)

1. Nearest neighbours by embedding among already-placed entries, from
   `CorpusStorePort`.
2. `CompletionPort` chooses an existing owned folder that is not `locked`,
   or proposes one new leaf under an existing owned folder, given the
   neighbours and their folders, the `TreeOutline`, and the most recent
   `MoveFeedback` examples.
3. A proposed leaf that collides with an existing name at the same level
   resolves to the existing folder.
4. The placement and its reason are recorded before `file` builds a batch.

Placement never moves an existing item. Only an accepted `DiffItem` or an
undo moves what is already filed.

### Multi-device policy

| Folder | Who writes | Who reads |
|---|---|---|
| `Follow Up` | any device adds (phone included); the writer host moves items out | every host's daemon ingests from it |
| `Dynomark` | the writer host only | every device, through sync |
| `Graveyard` | the writer host only | every device |
| rest of the tree | the user; the writer host only inside an accepted `audit` item | every device |

One writer means no claiming and no cross-host de-duplication. A `reader`
host's daemon ingests every save it sees for its own search and chat, keyed
on the create event, and completes regardless of where the node moves
afterwards. Tab capture happens only on the host where the save was made;
the writer host captures a save made elsewhere by fetch, which loses
logged-in content (Key Decisions). Changing the writer moves `HostRole` on
two hosts; the new writer rebuilds `owned_folder` from the tree by name, and
undo does not cross a writer change.

### Module map (phase 3)

| Layer | Extension runtime | Daemon runtime |
|---|---|---|
| Domain | tree model, `OwnedRoots` boundary check, path-idempotent operations, tiered fuzzy+frecency ranking | tree model (same language), placement rule, hybrid fusion, `TreeDiff`, batch construction and inverse, undo guard |
| Application (use cases) | `capture`, `submit_save`, `search_local`, `search_remote`, `sync_index`, `apply_batch`, `ack_batch`, `record_move` | `ingest`, `capture`, `process_job`, `place`, `file`, `undo`, `receive_receipt`, `search_corpus`, `ask`, `propose_diff`, `accept_diff_item`, `explain_placement`, `build_local_index` |
| Ports | `BookmarkTreePort`, `HistoryPort`, `ContentSourcePort`, `TransportPort` | `TransportPort`, `ContentSourcePort`, `CorpusStorePort`, `EmbeddingPort`, `CompletionPort` |
| Composition root | the extension's background entry point wires the browser adapters and the transport adapter; the chat page is a view over it | the daemon's main loads `Config` and wires the transport, store, model and content adapters |

The domain is expressed twice because the runtimes cannot share a process;
the language is one, and each side tests its domain in isolation.

---

## Behaviors and Interfaces

Signatures are language-neutral; inputs and outputs are the nouns above.
Ports arrive as keyword dependencies after the values. `role: HostRole` is
a value input wherever a batch could result.

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| Content is captured from the open tab | `capture(bookmark: Bookmark, *, content: ContentSourcePort) -> Capture` | `ContentSourcePort` | Given a tab showing the URL, When captured, Then `source` is `tab` and text is non-empty |
| Content falls back to fetch | (same use case, daemon side, fetch adapter) | `ContentSourcePort` | Given a request whose capture has `source` `none`, When captured, Then `source` is `fetch`; if the fetch fails, `source` stays `none` and the job continues |
| A save is submitted | `submit_save(bookmark: Bookmark, capture: Capture, *, transport: TransportPort) -> RequestId` | `TransportPort` | Given a new `Follow Up` node, When submitted twice, Then the daemon holds one job |
| A save is ingested | `ingest(bookmark: Bookmark, capture: Capture, *, store: CorpusStorePort) -> Job` | `CorpusStorePort` | Given a bookmark, When ingested, Then a `Job` is `QUEUED`; a second ingest with the same (`NodeId`, `Identity`) returns the same job |
| A duplicate identity is parked | `ingest` (same use case) then `file` | `CorpusStorePort` | Given an identity already `FILED`, When the new node is ingested on the writer, Then the batch moves the new node to `Graveyard` and the existing placement is unchanged |
| A job is processed to an entry | `process_job(job: Job, *, store: CorpusStorePort, embedding: EmbeddingPort, completion: CompletionPort) -> CorpusEntry` | `CorpusStorePort`, `EmbeddingPort`, `CompletionPort` | Given a job with a capture, When processed, Then the entry has summary, tags and embedding and `search_corpus` finds a word only in the captured text |
| A failed enrichment is retried, then parked | (same use case; error path) | as above | Given a completion that errors `RetryPolicy.attempts` times, When processed, Then the job is `FAILED` and no `write_batch` references its identity |
| An entry is placed | `place(entry: CorpusEntry, outline: TreeOutline, feedback: list[MoveFeedback], role: HostRole, *, store: CorpusStorePort, embedding: EmbeddingPort, completion: CompletionPort) -> Placement or NotWriter` | `CorpusStorePort`, `EmbeddingPort`, `CompletionPort` | Given three placed neighbours in one folder and a fake completion echoing it, When placed, Then the placement names that folder and its reason lists the neighbours |
| Placement respects a lock | (same use case) | as above | Given the fake completion names a `locked` folder, When placed, Then the result is a sibling or new leaf, never inside it |
| A placement becomes a batch | `file(placement: Placement, outline: TreeOutline, roots: OwnedRoots, role: HostRole) -> WriteBatch or NotWriter` | none | Given a placement under `Dynomark`, When filed, Then a batch with create-folder, move and their inverse exists in `PROPOSED` |
| An out-of-boundary batch is unconstructible | (same use case; error path) | none | Given a placement path outside `OwnedRoots` and no accepted item, When filed, Then it raises and no batch row exists |
| A batch is applied | `apply_batch(batch: WriteBatch, *, tree: BookmarkTreePort) -> BatchReceipt` | `BookmarkTreePort` | Given a batch, When applied, Then a snapshot is read first, operations run in order, and the receipt is `APPLIED` with a node id per operation |
| A batch resumes after termination | (same use case) | `BookmarkTreePort` | Given a cursor at operation 3 of 5, When the same batch is offered again, Then operations 1-3 are not repeated and the receipt is `APPLIED` |
| A batch fails midway | (same use case; error path) | `BookmarkTreePort` | Given operation 3 fails, When applied, Then the receipt is `PARTIAL` with the applied prefix |
| A receipt is delivered | `ack_batch(receipt: BatchReceipt, *, transport: TransportPort) -> none` | `TransportPort` | Given a receipt, When delivered twice, Then the daemon records it once |
| A receipt is processed | `receive_receipt(receipt: BatchReceipt, *, store: CorpusStorePort) -> Job or WriteBatch` | `CorpusStorePort` | Given `APPLIED`, Then the job is `FILED` and the snapshot stored; Given `PARTIAL`, Then the job is `FAILED` and a `PROPOSED` inverse of the prefix exists |
| A user move becomes feedback | `record_move(move: Move, role: HostRole) -> MoveFeedback or none` | none | Given a `Move` of origin `user` between owned folders on the writer, When recorded, Then feedback exists; Given origin `extension` or role `reader`, Then none |
| Tier-1 search | `search_local(query: Query, index: LocalIndex, frecency: Frecency) -> list[Hit]` | none | Given 10,000 entries, When queried, Then every title match precedes every non-title match and the call is within Goal 4's tier-1 bound |
| Tier-2 search is requested | `search_remote(query: Query, *, transport: TransportPort) -> list[Hit]` | `TransportPort` | Given tier-1 returned under `tier2_min_hits`, When requested, Then hits have `tier` `corpus` |
| Tier-2 search | `search_corpus(query: Query, *, store: CorpusStorePort, embedding: EmbeddingPort) -> list[Hit]` | `CorpusStorePort`, `EmbeddingPort` | Given a word only in captured text, When queried, Then that entry is a hit, and fusion over the store's two candidate lists runs with a fake store |
| The local index is synced | `sync_index(*, transport: TransportPort) -> LocalIndex` | `TransportPort` | Given a changed corpus, When synced, Then the index has one row per entry, each at most 512 bytes |
| The local index is built | `build_local_index(*, store: CorpusStorePort) -> LocalIndex` | `CorpusStorePort` | Given the corpus, When built, Then rows hold exactly identity, title, path, tags, one-line summary |
| A question is answered with citations | `ask(question: Question, history: list[Turn], *, store: CorpusStorePort, embedding: EmbeddingPort, completion: CompletionPort) -> Answer` | `CorpusStorePort`, `EmbeddingPort`, `CompletionPort` | Given a fake completion citing the retrieved identities, When asked, Then each is a `Citation`; Given it cites an identity not retrieved, Then that one is dropped |
| An out-of-corpus URL is marked | (same use case) | as above | Given the completion returns a URL not in the corpus, When asked, Then the answer marks it `external` |
| A batch is undone | `undo(batch_id: BatchId, role: HostRole, *, store: CorpusStorePort) -> WriteBatch or NotWriter` | `CorpusStorePort` | Given an `APPLIED` batch and a user edit to nodes the batch did not touch, When undone, Then the inverse batch reverts every operation and the user edit is not among its targets |
| Undo skips a moved or vanished node | (same use case) | `CorpusStorePort` | Given one batch node was since moved or deleted by the user, When undone, Then that inverse operation is dropped and listed in the batch's report |
| Undo leaves a non-empty folder | (same use case) | `CorpusStorePort` | Given a folder the batch created now holds other items, When undone, Then its removal is dropped and reported |
| A diff is proposed | `propose_diff(kind: DiffKind, outline: TreeOutline, own_bar: TreeOutline, *, completion: CompletionPort) -> TreeDiff` | `CompletionPort` | Given the two outlines, When proposed, Then items exist and no batch exists |
| A diff item is accepted | `accept_diff_item(item: DiffItem, roots: OwnedRoots, role: HostRole) -> WriteBatch or NotWriter` | none | Given an item with `accepted_at` set, When accepted, Then a batch exists referencing that item; Given `accepted_at` unset, Then it raises |
| An audit item may cross the boundary | (same use case) | none | Given an accepted `audit` item targeting the user's bar, When accepted, Then the batch is admitted and its inverse carries the same item reference |
| A placement is explained | `explain_placement(identity: Identity, *, store: CorpusStorePort) -> PlacementReason` | `CorpusStorePort` | Given a filed entry, When explained, Then the reason names the folder, neighbours and feedback used |
| A reader host never writes | `place`, `file`, `undo`, `accept_diff_item` with `role` `reader` | none | Given role `reader`, When any of them runs, Then the result is `NotWriter` and no batch row exists |

---

## State Machine

The `Job` is the lifecycle-bearing entity.

```
 +--------+   +-----------+   +----------+   +--------+   +-------+
 | QUEUED |-->| CAPTURING |-->| ENRICHED |-->| PLACED |-->| FILED |
 +--------+   +-----------+   +----+-----+   +--------+   +-------+
      |             |              |   |          |
      |             |              |   +----------+-----> +---------+
      |             |              |   (role reader)      | INDEXED |
      |             |              |                      +---------+
      +------+------+--------------+--------------+
             v  (retries exhausted; PARTIAL or REJECTED receipt)
         +--------+
         | FAILED |----> QUEUED  (user retries)
         +--------+
```

| From | To | Trigger | Condition |
|---|---|---|---|
| QUEUED | CAPTURING | job picked up | any host |
| CAPTURING | ENRICHED | capture resolved (`tab`, `fetch`, or `none` after fetch gave up) and entry enriched | ports returned |
| ENRICHED | INDEXED | entry indexed | `HostRole` is `reader`; terminal; `place` is not called |
| ENRICHED | PLACED | placement recorded | `HostRole` is `writer` |
| PLACED | FILED | `APPLIED` receipt | terminal |
| QUEUED, CAPTURING, ENRICHED, PLACED | FAILED | retries exhausted, or `PARTIAL` / `REJECTED` receipt | node stays where it is; on `PARTIAL` an inverse of the prefix is offered |
| FAILED | QUEUED | user retries from chat or menu | always allowed |

A batch has its own states, `PROPOSED -> APPLIED | PARTIAL | REJECTED`, in
the transport contract. A `DiffItem` is `proposed -> accepted`.

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

corpus_entry
+-- identity          FK bookmark, unique
+-- summary, tags[]
+-- embedding         vector, with the model id that produced it
+-- indexed_at

placement
+-- identity, folder_path
+-- reason            neighbours, rationale, feedback ids, model id
+-- created_at

owned_folder
+-- stable_id, folder_path, node_id (this host), pinned, locked

move_feedback
+-- identity, from_path, to_path, observed_at

job
+-- job_id, node_id, identity, state, attempts, last_error, updated_at

tree_diff
+-- diff_id, kind (audit | rebuild), proposed_at

diff_item
+-- item_id           FK tree_diff
+-- operations[], accepted_at or none

write_batch
+-- batch_id, operations[], inverse[]
+-- state             PROPOSED | APPLIED | PARTIAL | REJECTED
+-- receipt           node ids per operation, or applied prefix, or reason
+-- snapshot_id or none, diff_item_id or none
+-- report            inverse operations dropped by the undo guard

snapshot
+-- snapshot_id, taken_at, tree (full tree as read by the extension)

extension-side (rebuildable or small):
local_index           one row per corpus_entry, <= 512 bytes each
batch_cursor          batch_id, applied operation index
settings              transport selection, Follow Up behaviour
```

Constraints: one `corpus_entry` per `identity`; every `write_batch`
operation targets a path under `OwnedRoots` unless `diff_item_id` names an
item with `accepted_at` set and every such operation is inside that item;
`owned_folder.stable_id` never changes once assigned.

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
  captured text. Mitigation: owner-only permissions in the user's state
  directory; never synced or backed up by Dynomark; excluded from any repo.
- **Cloud model egress** -- summaries and questions may leave the machine.
  Mitigation: model choice is per install and per port, local is the
  default, and the setting is shown in the chat surface.
- **Transport exposure** -- the native-messaging shim is bound to the
  extension's identity in the host manifest; the daemon's unix socket is
  owner-only; no TCP port. A remote adapter is a separate record behind the
  Access gate.
- **Tree damage** -- the boundary policy runs before a batch exists; every
  batch has a recorded inverse and a preceding snapshot; removals go to
  `Graveyard`; operations are path-idempotent so a resumed batch cannot
  double-create.
- **Daemon-side fetch** -- carries no cookies and follows the same
  non-http(s) exclusion.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Source of truth | the native browser bookmark tree | no new app to live in; sync to every device, phone included, comes free |
| Process split | thin extension owns tree writes; long-lived daemon owns capture, corpus, models | the extension runtime cannot run long jobs; a daemon behind a native-messaging shim can, whether or not the browser is connected |
| Multi-device | one shared `Dynomark` folder, one `writer` host | per-host folders duplicate the hierarchy on every device and force a claiming protocol; one writer needs neither |
| Phone | a consumer: saves into `Follow Up`, reads `Dynomark` via sync | mobile browsers run no extension; this gives capture and browse with zero mobile software |
| Corpus locality | one corpus per daemon; only the writer files | local search and chat on every laptop without a corpus sync problem |
| Tab capture locality | tab capture only where the save happened; the writer fetches saves made elsewhere | there is no cross-host channel; logged-in content from other devices is a known loss (Open Questions) |
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

---

## Open Questions

1. **`Follow Up` semantics after filing** -- consume the item, or keep it as
   a to-do with states (new, processed, read, done) and resurfacing?
2. **Two hosts configured as writer** -- detect via a marker the writer
   leaves in the owned tree and refuse, or last-configured wins?
3. **Logged-in content saved on a non-writer device** -- accept the fetch
   loss, or let a reader host forward its tab capture to the writer over a
   future remote transport?
4. **Merge rules for audit** -- undefined for v1 by intent; learned from use.
5. **Rebuild cadence** -- manual only, or a slow default schedule?
6. **Backfill** -- run the existing tree through capture and indexing at
   first install (searchable, not re-filed), and at what rate?
7. **Default models** -- which local embedding and completion models ship
   as defaults.
8. **Firefox timing** -- after which phase the second browser adapters are
   worth building.

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
  behind the fleet's Access gate, its own design record; also the channel
  a reader host could use to forward tab captures (Open Question 3).
- **Firefox** -- second `BookmarkTreePort` and `HistoryPort` adapters; the
  sidebar is the natural chat surface there.
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
