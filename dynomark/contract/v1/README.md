# Dynomark transport contract, version 1

The wire contract between the Dynomark extension and the Dynomark daemon
(`docs/design/DYNOMARK.DESIGN.md`, "Transport contract"). Two runtimes
implement it independently -- a Python daemon (Pydantic models) and a
TypeScript MV3 extension (zod schemas) -- and this directory is the only
thing they share. Where this README and `messages.schema.json` disagree,
that is a bug in the contract; fix both in one change.

| File | What it is |
|---|---|
| `CONTRACT_VERSION` | The single integer `1` |
| `messages.schema.json` | JSON Schema draft 2020-12: one `$defs` entry per message and per shared value; the root is a `oneOf` over every message, discriminated by `type` |
| `examples/valid/<type>[--<variant>].json` | Documents every runtime MUST accept; at least one per message type |
| `examples/invalid/<rule>.json` | Documents every runtime MUST reject, each breaking one named rule |
| `examples/invalid-rules.json` | For each invalid file: the JSON Schema keyword and instance path that rejects it |
| `../check.py` | Zero-dependency self-check of this directory (below) |

Keywords used by the schema are limited to: `$ref`, `$defs`, `type`,
`const`, `enum`, `properties`, `required`, `additionalProperties` (always
`false` on an object), `items`, `minItems`, `maxItems`, `uniqueItems`,
`minLength`, `maxLength`, `pattern`, `minimum`, `maximum`,
`minProperties`, `oneOf`, `anyOf`, `allOf`, `not`, `if`/`then`/`else`.
Every `pattern` is anchored `^...$` and uses only character classes and
counted repetition. `pattern` means "the whole string matches", as in
ECMA-262: a Python implementation MUST use `re.fullmatch` (or Pydantic's
default Rust regex engine), never `re.match`/`re.search` with the raw
pattern, whose `$` also matches before a trailing newline
(`invalid/request-id-trailing-newline.json`).

---

## Framing

Both hops -- Chrome/Firefox native messaging on the shim's stdio, and the
daemon's unix socket -- carry the same frames:

```
+------------------------------+-------------------------------------+
| length: uint32 LITTLE-endian | length bytes of UTF-8 JSON (no BOM) |
+------------------------------+-------------------------------------+
```

- One frame is exactly one JSON object that is one message below.
  Length 0 is invalid.
- The native-messaging host is a transparent byte pipe: it copies frames
  between its stdio and the socket unchanged, in both directions, and
  never parses them. (Native messaging uses native byte order; every
  supported host is little-endian, and the socket hop is pinned
  little-endian so the pipe needs no conversion.)
- Size limits are on the JSON body's byte length; the 4-byte header is
  not counted (as in Chrome's own check):
  - daemon -> extension: at most 1 MiB (1,048,576 bytes), Chrome's limit
    for a message from a native host. Everything that can grow is
    paginated (`index.pull`, `search`, `diff.page`, `outline.get`, and
    the `*.list` requests).
  - extension -> daemon: at most 32 MiB (33,554,432 bytes); a full
    `Snapshot` travels this way.
- A receiver that reads a length over its limit, or a body that is not a
  JSON object, closes the connection without answering; the sender
  reconnects. A body that is a JSON object but fails the schema is
  answered with `error` code `invalid` (`re` is the request's `id` if it
  can be read as an `Id`, else `null`).
- JSON: duplicate keys are invalid; integers are within +/- 2^53 - 1;
  string lengths in the schema count Unicode code points (a JS runtime
  counts `[...s].length`, not `s.length`).
- Every string on the wire is a sequence of Unicode scalar values: no
  lone UTF-16 surrogate, escaped or not. Browser data can hold them (a
  title cut mid-emoji), so the extension MUST make every string
  well-formed (`String.prototype.toWellFormed`, lone surrogates ->
  U+FFFD) before sending. A frame with a lone surrogate is `invalid`.

## Endpoint

- The daemon listens on the unix socket `$DYNOMARK_SOCKET` when set,
  else `${XDG_STATE_HOME:-$HOME/.local/state}/dynomark/daemon.sock`. The
  directory is mode 0700, the socket 0600. No TCP port exists.
- The native-messaging host name is `tds.dynomark`. The browser starts
  the shim; the shim connects to the socket and pipes.
- One connection per browser profile. Node ids are per profile, so every
  `hello` names its `profile_id`, and the daemon binds each ingest, job,
  batch and event to that profile. A `hello` answered with mode `full`
  or `read_only` supersedes any earlier connection with the same
  `profile_id`: the daemon sends that older connection `error`
  `superseded` (`re` null) and closes it. An extension that receives
  `superseded` does not reconnect that connection. Connections of
  different profiles coexist.

## Envelope

Every message is a flat JSON object with these envelope fields plus its
own body fields:

| Field | Type | On | Meaning |
|---|---|---|---|
| `v` | integer | every message | The sender's contract version. Pinned to `1` in every message except the three frozen ones (`hello`, `hello.result`, `error`), which accept any `v >= 1` |
| `type` | string | every message | The message type; the discriminator |
| `id` | `Id` | requests | Caller-chosen request id (extension side). A retry of the same request reuses the same `id` and body |
| `re` | `Id` | responses | The `id` of the request this answers (`error` only: `null` when unreadable, and for `superseded`) |
| `event_id` | `Id` | events | Daemon-chosen, unique in the daemon's store, never reused; durable until acknowledged |

A message has exactly one of `id`, `re`, `event_id`, and that fixes its
direction: requests go extension -> daemon; responses and events go
daemon -> extension. The daemon never sends a request; the extension
never sends a response or an event.

**Request ids** are unique for the lifetime of the daemon store: the
extension generates each one randomly with at least 122 bits of entropy
(a UUIDv4 or a ULID) and never reuses one for a different body. The
examples use short ids for readability. The daemon remembers a
`diff.propose` id for as long as it keeps the diff; a known
`diff.propose` id arriving with a different body is answered `error`
`invalid`.

Every request `X` is answered by exactly one frame: `X.result` or
`error`, with `re` = the request's `id`. Responses may arrive in any
order relative to other requests' responses, and events interleave
freely. A request that changes daemon state is answered `X.result` only
after its effect is durable in the daemon store.

Frozen messages: `hello`, `hello.result` and `error` keep their v1 shape
in every future version, so any two versions can always complete the
handshake and read an error.

Conventions: optional fields are omitted, never `null`; `null` appears
only where the schema says `null` (end of pagination, the browser root's
`parent_id`, an unaccepted `DiffItem`, an `undo` that dropped
everything, an unreadable or unsolicited `re`). Times are `EpochMs`. Ids
are opaque: compare byte-for-byte, never parse.

**Identity.** An `Identity` is computed only by the daemon, and it is an
absolute URL that the browser can navigate to and that reaches the same
resource as the raw URLs it stands for (normalization only removes
equivalent variants). The extension never computes one: it opens a
tier-1 or tier-2 hit, or a citation, by navigating to its identity, and
builds `Frecency` by asking `HistoryPort` for the visits of each
identity it holds, never by normalizing history URLs.

## Connection lifecycle

1. The extension connects and sends `hello` with its `v`, its
   `profile_id` (generated once, kept in its settings) and the
   `Follow Up` folder it resolved (zero folders named `Follow Up`:
   create one under the bookmarks bar first; several: use the one under
   the bookmarks bar).
2. The daemon answers `hello.result` with its own `v`, `host_id`,
   `role`, `owned_roots`, and `mode`. `owned_roots.follow_up` MUST equal
   `hello.follow_up` exactly. `role` is the role this connection is
   served with: a writer daemon files for one profile, the profile its
   store is bound to (the first `profile_id` to complete a `full` hello;
   rebinding is a user action on the daemon, outside this contract), and
   answers `role` `reader` to every other profile.

   | Versions | `mode` | What continues |
   |---|---|---|
   | equal | `full` | everything |
   | extension newer than daemon | `read_only` | the read-only set only, spoken at the daemon's version |
   | extension older than daemon | `refused` | nothing but `hello` |

   Read-only set: `hello`, `status`, `events.replay`, `events.ack`,
   `index.pull`, `search`, `ask`, `placement.explain` -- the design's
   "search and chat continue". In `read_only` any other request is
   answered `error` `version_mismatch`, and the only event the daemon
   sends is `job.updated`, at its own version. In `refused`, every
   request but `hello` is answered `version_mismatch` and the daemon
   sends no event at all.
3. The daemon checks every request in this order, and the first rule
   that applies decides the answer:
   1. body not a JSON object (or over the size limit) -> close, no answer;
   2. read `id` (when it is not a readable `Id`, `re` is `null` below);
   3. no `hello` answered yet on this connection and `type` is not
      `hello` -> `hello_required`;
   4. `type` is a known non-frozen message whose `v` is an integer other
      than the daemon's, or a request outside the connection's `mode` ->
      `version_mismatch`;
   5. the full schema -> `invalid`.

   A second `hello` on a connection is answered again and changes
   nothing else.
4. In `full` mode the extension then sends `tree.snapshot` and
   `events.replay`, and pulls the index (`index.pull` from the first
   page). The daemon sends no event before it has answered `hello`, and
   no `batch.offer` on a connection until it has recorded a
   `tree.snapshot` received on that connection and re-evaluated writer
   markers against it; after that it may push live events at any time.
5. Because `ingest` is idempotent, the extension MAY re-send `ingest`
   for every node currently in `Follow Up` after a `full` hello; the
   daemon treats repeats as no-ops.
6. The extension sends `tree.snapshot` after every `hello`, right after
   every `batch.receipt.result` (not debounced), immediately before every
   `diff.propose` (awaiting `tree.snapshot.result` first, so an audit
   compares against the current bar), and debounced after changes under
   the owned roots.

## Message table

| Message type | Direction | Purpose | Design use case |
|---|---|---|---|
| `hello` | extension -> daemon | Open the connection: extension's contract version, `profile_id` and resolved `Follow Up` | Transport contract: identity and version |
| `hello.result` | daemon -> extension | Daemon's version, host id, the connection's `HostRole`, `OwnedRoots`, connection mode | Transport contract: identity and version; One writer (Goal 7) |
| `ingest` | extension -> daemon | Submit a save with its raw URL, optional `Capture`, backfill flag | A save is submitted; A save is ingested; Content is captured from the open tab; Open Question 3 (backfill) |
| `ingest.result` | daemon -> extension | The `Job` for the save (the existing one on a repeat) | A save is ingested; A duplicate identity is parked |
| `job.retry` | extension -> daemon | User retry of a `FAILED` job | State Machine: FAILED -> QUEUED |
| `job.retry.result` | daemon -> extension | The job after the retry | State Machine: FAILED -> QUEUED |
| `job.list` | extension -> daemon | One page of jobs, optionally in one state (the retry view lists `FAILED`) | State Machine: FAILED -> QUEUED; Transport contract: retryable errors (surface in chat) |
| `job.list.result` | daemon -> extension | One page of `Job`s | State Machine: FAILED -> QUEUED |
| `job.updated` | daemon -> extension | Event: a job changed state | Transport contract: direction (job finished); A failed enrichment is retried, then parked |
| `tree.snapshot` | extension -> daemon | The full tree: after hello, after each receipt result, before each `diff.propose`, after owned-root changes (debounced) | An entry is placed (outline source); A diff is proposed; Undo guard; Writer marker |
| `tree.snapshot.result` | daemon -> extension | Snapshot recorded | An entry is placed |
| `move.observed` | extension -> daemon | A move between owned folders, with `origin` user or extension | A user move becomes feedback |
| `move.observed.result` | daemon -> extension | Move recorded or discarded | A user move becomes feedback |
| `batch.offer` | daemon -> extension | Event: a `WriteBatch` to apply | A placement becomes a batch; Transport contract: partial failure (re-offer) |
| `batch.receipt` | extension -> daemon | `BatchReceipt` (`APPLIED` / `PARTIAL` / `REJECTED`) with the snapshot read at the start of the attempt | A batch is applied; A batch resumes after termination; A batch fails midway; A receipt is delivered |
| `batch.receipt.result` | daemon -> extension | Receipt recorded (once per batch) | A receipt is delivered; A receipt is processed |
| `batch.list` | extension -> daemon | One page of write batches, newest first | A batch is undone; Transport contract: `REJECTED` and `PARTIAL` surface in chat and the diff view |
| `batch.list.result` | daemon -> extension | One page of `BatchSummary`s | A batch is undone |
| `events.replay` | extension -> daemon | Re-send every unacknowledged event | Transport contract: delivery |
| `events.replay.result` | daemon -> extension | Sent after the replayed events; how many | Transport contract: delivery |
| `events.ack` | extension -> daemon | Acknowledge `job.updated` and `diff.proposed` events | Transport contract: delivery |
| `events.ack.result` | daemon -> extension | Acknowledged | Transport contract: delivery |
| `index.pull` | extension -> daemon | Pull one page of the `LocalIndex` | The local index is synced |
| `index.pull.result` | daemon -> extension | One page of `LocalIndexRow`s | The local index is synced; The local index is built |
| `search` | extension -> daemon | Tier-2 query, paginated | Tier-2 search is requested |
| `search.result` | daemon -> extension | One page of corpus `Hit`s | Tier-2 search |
| `ask` | extension -> daemon | A `Question` plus history | A question is answered with citations |
| `ask.result` | daemon -> extension | `Answer` with `Citation`s and external URLs | A question is answered with citations; An out-of-corpus URL is marked |
| `placement.explain` | extension -> daemon | Why an entry is where it is ("why here") | A placement is explained |
| `placement.explain.result` | daemon -> extension | The `PlacementReason` | A placement is explained |
| `undo` | extension -> daemon | Undo an `APPLIED` batch | A batch is undone |
| `undo.result` | daemon -> extension | The inverse batch id and the guard's dropped operations | A batch is undone; Undo skips a moved or vanished node; Undo leaves a non-empty folder |
| `diff.propose` | extension -> daemon | Propose an `audit` or `rebuild` `TreeDiff` | A diff is proposed |
| `diff.propose.result` | daemon -> extension | The diff header | A diff is proposed |
| `diff.list` | extension -> daemon | One page of `TreeDiff` headers, newest first | A diff is proposed; Config: rebuild cadence |
| `diff.list.result` | daemon -> extension | One page of `TreeDiff`s with their unaccepted counts | A diff is proposed |
| `diff.proposed` | daemon -> extension | Event: the daemon proposed a diff on its own schedule | Config: rebuild cadence; Open Question 2 |
| `diff.page` | extension -> daemon | Read one page of a diff's items | A diff is proposed |
| `diff.page.result` | daemon -> extension | One page of `DiffItem`s, each accepted one with its batch and batch state | A diff is proposed; Transport contract: `REJECTED` and `PARTIAL` surface in the diff view |
| `diff.accept` | extension -> daemon | Accept one `DiffItem` (item id only) | A diff item is accepted; An audit item may cross the boundary |
| `diff.accept.result` | daemon -> extension | Recorded `accepted_at` and the batch it produced | A diff item is accepted |
| `outline.get` | extension -> daemon | Read one page of the owned `TreeOutline` | Glossary: `pinned`, `locked` (settings view) |
| `outline.get.result` | daemon -> extension | One page of `OutlineFolder`s | Glossary: `pinned`, `locked` |
| `folder.flags.set` | extension -> daemon | Set `pinned` / `locked` on an owned folder, by node id | Placement respects a lock; pinned folders immune to diffs |
| `folder.flags.set.result` | daemon -> extension | The folder with its flags | Placement respects a lock |
| `writer.status` | extension -> daemon | Writer-marker status | Key Decisions: two writers (MVP writer marker) |
| `writer.status.result` | daemon -> extension | Own marker, other writers, conflict flag | Key Decisions: two writers (MVP writer marker) |
| `status` | extension -> daemon | Daemon status for the settings page | Security: cloud model egress shown; Config |
| `status.result` | daemon -> extension | Role, host id, contract version, models, queue depth | Security: cloud model egress shown; Config |
| `error` | daemon -> extension | The one error response, closed code set | A reader host never writes (`not_writer`); Transport contract: retryable errors |

## Delivery and replay

- **Requests are at-least-once.** The extension re-sends a request that
  has no answer after a reconnect, with the same `id` and body. Every
  request that changes daemon state has a natural idempotency key
  (below), so a repeat is harmless. One exception: pending
  `batch.receipt`s do not survive an extension restart (a receipt holds a
  snapshot of up to 32 MiB). After a restart the extension answers the
  re-offered `batch.offer` with a freshly derived receipt under a new
  request id; the first receipt the daemon records wins.
- **Events are durable until acknowledged.** `job.updated` and
  `diff.proposed` are acknowledged by `events.ack`; a `batch.offer` only
  by a `batch.receipt` for its `batch.batch_id` (an `events.ack` naming
  it is ignored for that id). Unknown and already-acknowledged ids in
  `events.ack` are ignored. Events go only to a connection of the
  profile they belong to.
- **Replay.** `events.replay` makes the daemon re-send every
  unacknowledged event, oldest first, as ordinary event frames, then
  answer `events.replay.result` with the count. The daemon may also
  re-push an unacknowledged event at any time. Both omit `batch.offer`
  while the connection's `mode` is not `full`, its `role` is `reader`,
  the writer is in conflict, or no `tree.snapshot` has been recorded on
  the connection; those batches stay `PROPOSED` and unacknowledged.
- **De-duplication.** The extension de-duplicates the side effects of
  `job.updated` and `diff.proposed` by `event_id`. Of two copies of one
  job it keeps the one with the higher `seq`, whatever order they arrive
  in. `batch.offer` is never de-duplicated away: every offer frame, a
  repeated `event_id` included, is answered with a `batch.receipt` (see
  Cursor and resume).
- **Index freshness.** The extension re-pulls the whole `LocalIndex`
  (from the first page) after a `full` hello and after any `job.updated`
  whose state is `FILED` or `INDEXED`; it swaps the new index in only
  when the last page (`next_cursor` null) arrives. A `job.updated` that
  arrives during a pull does not restart it: the extension finishes the
  pull, then starts one more.
- **Pagination.** A cursor is opaque and valid only for the message type
  and the request parameters (`query`, `diff_id`, `state`) that minted
  it; presented with others it is answered `error` `stale_cursor`.
  `index.pull` cursors MUST stay valid across data changes (keyset by
  identity, or snapshot-consistent). For the other paginated requests,
  when the underlying data changes between pages the daemon MAY answer
  `stale_cursor`. Either way the extension restarts from the first page.
  `limit` is an upper bound; the daemon returns fewer rows whenever
  needed to keep the frame within 1 MiB. `search` repeats its `query` on
  every page.

| Request | Idempotency key | A repeat... |
|---|---|---|
| `ingest` | (profile, `bookmark.node_id`, identity of `bookmark.url`) | returns the same job; nothing new is queued |
| `job.retry` | `job_id` | on a job not `FAILED`, changes nothing |
| `tree.snapshot` | `snapshot.taken_at` | the daemon keeps the snapshot with the latest `taken_at` |
| `move.observed` | (`move.node_id`, `move.observed_at`) | records nothing new |
| `batch.receipt` | `receipt.batch_id` | records nothing new; the first receipt recorded wins |
| `events.ack` | each event id | is a no-op |
| `undo` | `batch_id` | returns the same recorded inverse batch; at most one inverse per batch. An all-dropped answer (`batch_id` null) is not recorded, so a later `undo` re-evaluates |
| `diff.propose` | request `id` | with the same `id` returns the same diff; a new `id` proposes a new one |
| `diff.accept` | `item_id` | returns the same `accepted_at` and batch |
| `folder.flags.set` | (`node_id`, flag values) | sets the same values |
| all others | none needed | are read-only |

## Jobs

- **Backfill.** An `ingest` with `backfill` true is never offered a
  batch. On a writer, a backfill whose `bookmark.path` is
  `owned_roots.dynomark` or inside it records a placement at that path
  and ends `FILED` with no `batch_id` -- this is how a new writer learns
  what is already filed. Every other backfill ends `INDEXED`.
- **Receipt -> job.** The filing op of a job is the op of its batch whose
  `node_id` is the job's node (the `move` into `Dynomark`, or the
  `remove` that parks a duplicate).

  | Receipt | Job | Also |
  |---|---|---|
  | `APPLIED`, filing op in `applied` | `FILED` | store node ids and snapshot |
  | `APPLIED`, filing op in `skipped` | `FAILED`, `last_error` names the skip reason | offer the inverse of the applied ops with `changed` true, as for `PARTIAL` |
  | `PARTIAL` | `FAILED` | offer the inverse of the applied ops with `changed` true; none when there are none |
  | `REJECTED` | `FAILED` | nothing |

- **Duplicate identity.** An identity counts as already filed only when
  it has a `FILED` entry whose node is present in the latest
  `tree.snapshot`.

## Write batches

The daemon never touches the tree; the extension applies `WriteBatch`es
offered by `batch.offer`, one batch at a time, in the order offered.

**Paths.** A `FolderPath` is `{root, names}`: `root` is a `RootKey`
(`bar`, `other`, `mobile`, `menu`) and `names` are folder titles
downward. The node a `RootKey` maps to is exactly `Snapshot.root_ids`
of the extension's snapshots on that connection (Chrome: bookmarks bar /
other / mobile; Firefox: toolbar / unfiled / mobile / menu); where the
browser exposes both an account (syncing) and a local-only copy of a
top-level folder, it is the syncing copy. Resolution picks, at each
level, the child *folder* (never a bookmark or separator) with the
lowest index whose title equals the name exactly, comparing the
well-formed titles. `names: []` is the top-level folder itself.

**Operations** (each carries `index`, and `batch.operations[i].index ==
i`):

| `op` | Fields | Applies as | Node id in the receipt |
|---|---|---|---|
| `create_folder` | `parent`, `title` | create folder `title` in `parent` unless a child folder with that exact title exists; `parent` must exist | the folder |
| `create` | `parent`, `title`, `url` | create a bookmark in `parent` unless a child bookmark with that exact `url` exists; `parent` must exist. `url` is exactly as a browser reported it (a `Bookmark.url` or an untruncated `SnapshotNode.url`), never an `Identity` | the bookmark |
| `move` | `node_id`, `to`, `expect` | move the node to the end of `to` unless it is already directly in `to`; `to` must exist | `node_id` |
| `remove` | `node_id`, `expect` | move the node to the end of `owned_roots.graveyard` (this connection's `hello.result`) unless already directly in it; never deletes | `node_id` |

**Preconditions.** Every `move` and `remove` carries `expect` with at
least `parent_id` (its parent node id), plus optionally `parent_path`
(the node is directly in the folder that path resolves to) and
`empty: true` (it is a folder with no children). For a `move` or
`remove` the extension first tests whether the node is already directly
in the target folder: if so the op is `applied` with `changed` false and
`expect` is not evaluated. Otherwise it checks every `expect` clause; if
any fails, or the node no longer exists, the op is **skipped** -- listed
in `skipped` with a `SkipReason` -- and the batch continues. This is how
a guarded undo re-checks itself at apply time. Any op whose target
folder does not resolve, or that the browser refuses, **fails**: the
batch stops and the receipt is `PARTIAL`.

**Boundary.** Before the first op, the extension checks every op against
`owned_roots`, and a batch with `diff_item_id` is exempt. The check is
syntactic on paths: a `FolderPath` P is inside an owned root R when
`P.root == R.root` and `R.names` is a prefix of `P.names` (P == R
included).

- The target folder (`parent`, `to`; for `remove`, the graveyard) must
  be inside an owned root. Exception: a `create_folder` whose (`parent`,
  `title`) is exactly an owned root (`parent` is that root's path minus
  its last name, `title` its last name) is admitted -- this is how the
  daemon creates `Dynomark` and `Graveyard` on a fresh tree.
- For `move` / `remove` of a node that exists at check time, one of its
  ancestors-or-self folders, starting at its parent, must be the node an
  owned root resolves to. A node missing at check time passes the
  boundary and is handled by its op (skipped: it carries `expect`).

If any op fails the check the batch is `REJECTED` (`boundary`) and
nothing is touched. A batch whose op indices are not `0..n-1` is
`REJECTED` (`invalid`). A batch arriving while `owned_roots.dynomark`
holds a `dynomark-writer:` folder of a host other than this connection's
`hello.result` `host_id` is `REJECTED` (`writer_conflict`).

**Inverses.** The daemon keeps each batch's inverse; the undo inverse
and the `PARTIAL`-prefix inverse revert only ops reported `applied` with
`changed` true. Every inverse batch carries the original batch's
`diff_item_id` when the original had one, so reverting an accepted audit
item crosses the boundary exactly as the item did
(`batch.offer--partial-inverse-audit.json`). A `PARTIAL` or skipped
filing with no `changed` op produces no inverse batch (a batch has at
least one op).

**Undo guard.** The daemon runs the undo guard only against a
`tree.snapshot` received after that batch's receipt was recorded;
before one arrives it answers `undo` with `busy`. A receipt's own
snapshot is stored as the batch's fallback export and never replaces
the latest `tree.snapshot`.

**One batch at a time.** The daemon has at most one `batch.offer`
unacknowledged per profile, and offers the next batch only after it has
durably recorded the previous batch's receipt. The extension keeps a
batch's cursor until `batch.receipt.result` (or `error` `not_found`) for
that `batch_id` arrives, and starts no other batch before then; an offer
of another batch that arrives meanwhile is held and applied, in the
order offered, after it.

**Cursor and resume.** The cursor is the design's in-flight batch
cursor: the `batch_id`, the next op index, the outcome of every op
before it (applied with node id and `changed`, or skipped with reason),
and an in-flight marker. For each op the extension:

1. decides without touching the tree whether the op is a no-op (already
   there: applied, `changed` false) or a skip; if so it records that
   outcome and moves on;
2. otherwise records (`batch_id`, i, started), makes the browser call,
   then records the outcome (applied, `changed` true) and i + 1.

When a batch whose `batch_id` the cursor names is offered again, the
extension does not repeat recorded ops: it reports their recorded
outcomes and resumes at the next index. An op marked started is
re-evaluated: if its post-condition holds (the folder or bookmark
exists, the node is directly in the target), it is applied with
`changed` true; otherwise it runs again under the normal rules. A batch
already fully applied -- the cursor names its `batch_id` with next index
`n` ("by cursor or by batch id") -- is answered `APPLIED` again from the
recorded outcomes without touching the tree. Outcomes are never
re-derived from the tree; if the cursor is lost the batch runs from op 0,
where path-idempotence makes recorded-less ops no-ops (`changed` false).

**Receipts.** `batch.receipt` carries a `BatchReceipt` discriminated by
`state`:

- `APPLIED`: `applied` (index, node id, `changed`) and `skipped` (index
  + reason) partition all op indices, each list ascending.
- `PARTIAL`: `applied` and `skipped` partition `0..failed.index-1`;
  `failed` names the op that failed and why; later ops were not tried.
- `REJECTED`: `reason` (`boundary`, `invalid` or `writer_conflict`);
  nothing was touched.

Every receipt carries `snapshot`, the full tree read at the start of
this apply attempt, and `pre_batch`: true only when no op of this batch
had changed the tree before that read (a resumed or re-answered batch
is `false`, `batch.receipt--resumed.json`). When `pre_batch` is false
the daemon records as the batch's snapshot the latest `tree.snapshot`
it recorded before it first offered the batch. A receipt that would not
fit the 32 MiB frame carries `snapshot_omitted: true` instead of
`snapshot`, with the same fallback. Moves the extension observes while
applying a batch, of nodes that batch's ops name, are reported with
`origin: extension`.

## Writer marker (MVP)

A writer daemon keeps a marker folder in the owned tree: an empty folder
titled exactly `dynomark-writer:<host_id>` directly in
`owned_roots.dynomark`, created by an ordinary `batch.offer`. The daemon
reads markers from the latest `tree.snapshot`, and re-reads them from
the first snapshot of every connection before offering on it. A writer
that sees another host's marker is in conflict: it offers no batches,
answers `undo`, `diff.accept` and `folder.flags.set` with `error`
`writer_conflict`, still accepts `ingest` (the job indexes, then ends
`FAILED` with a `last_error` naming the conflict), and reports it in
`writer.status.result`. The extension independently rejects any batch
while another host's marker is present (`writer_conflict`, above).
Marker folders are excluded from the `TreeOutline` and from placement.
Clearing a stale marker is a user edit in the tree.

## Roles and errors

| Code | Sent when | Retry |
|---|---|---|
| `version_mismatch` | a non-frozen message's `v` is not the daemon's; a request outside the connection's `mode` | no |
| `hello_required` | a request before `hello` was answered | after `hello` |
| `not_writer` | `undo`, `diff.accept` or `folder.flags.set` on a connection served as `reader` | no |
| `writer_conflict` | the same three on a writer that sees another host's marker | no |
| `not_found` | an unknown `job_id`, `batch_id`, `diff_id`, `item_id`, identity, url or folder node id (or a `folder.flags.set` whose `path` does not match its node) | no |
| `invalid` | a body that fails the schema, a reused `diff.propose` id with a different body, or a valid body the daemon cannot act on (e.g. `undo` of a batch that is not `APPLIED`, `folder.flags.set` outside the owned roots) | no |
| `stale_cursor` | a cursor that has expired, or presented with other request parameters | restart from page 1 |
| `busy` | temporarily unable (e.g. a model loading, or `undo` before a post-receipt `tree.snapshot`) | yes, same `id`, after backoff |
| `internal` | anything unexpected | yes, same `id`, after backoff |
| `superseded` | unsolicited (`re` null): a newer connection of the same profile replaced this one; the daemon closes this one | no; do not reconnect |

A connection served as `reader` answers `not_writer` only to the three
requests above and serves every other one: `ingest` indexes for its own
search and chat and never files (the job ends `INDEXED`),
`move.observed` is discarded for feedback, and no `batch.offer` is ever
sent.

## Size limits

| What | Limit |
|---|---|
| Frame, daemon -> extension | 1 MiB of JSON |
| Frame, extension -> daemon | 32 MiB of JSON |
| `LocalIndexRow` | 512 bytes, measured as the UTF-8 length of the row serialized as compact JSON (no whitespace, non-ASCII unescaped); the daemon trims `summary`, then `tags`, then `title`, and leaves out a row whose `identity` alone cannot fit |
| `Capture.text` | 1,048,576 code points |
| Titles (`Title`, `SnapshotNode.title`) | 4,096 code points |
| `Url`, `Identity`, `SnapshotNode.url` | 65,536 code points |
| `search.query` | 1 to 1,024 code points |
| `ask.question` | 1 to 8,192 code points; `history` at most 50 turns |
| Operations per batch | 1 to 1,000; per `DiffItem`, 1 to 100 |
| Page sizes | `index.pull`, `outline.get`, `job.list`: 1,000; `search`, `diff.page`, `diff.list`, `batch.list`: 100 |
| `events.ack` | 1 to 1,000 ids |
| Ids | `Id` 1 to 128 of `[A-Za-z0-9._:-]`; `NodeId` 1 to 64 of `[A-Za-z0-9._-]`; `HostId` 1 to 64, alphanumeric first; `Cursor` 1 to 1,024 printable ASCII, no space |

Browser data over a cap is handled by the extension before sending:
`Title`s and `Capture.text` are truncated at a code-point boundary; a
bookmark whose url exceeds the `Url` cap is not ingested (the extension
reports it locally); a `SnapshotNode` title or url over its cap is
truncated and the node marked `truncated: true`. A `tree.snapshot`
whose frame would still exceed 32 MiB is not sent (so no batch is
offered on that connection), and a receipt that would is sent with
`snapshot_omitted: true`.

The schema caps are upper bounds; they do not guarantee a daemon ->
extension frame fits 1 MiB. The daemon MUST NOT send a frame over the
limit: it shortens pages; in `ask.result` it drops trailing
`citations`, then `external_urls`, and in `placement.explain.result`
trailing `neighbours`, then `feedback_ids`, until the frame fits; a
single page row that alone cannot fit is left out of its page (the
cursor moves past it); and a batch it cannot fit is not offered (its job
fails with a `last_error` saying so,
`job.updated--failed-oversize-batch.json`).

## Validation

`python3 dynomark/contract/check.py` checks this directory against
itself with the Python standard library only (no `jsonschema`; it is not
on the tech radar): every message type has a valid example, every
example is valid JSON of a known type, every valid example passes and
every invalid example fails a small built-in validator for the keyword
subset above (for the reason `invalid-rules.json` names), op indices,
receipt partitions, 512-byte rows, frame limits, snapshot shape
(sibling indices, folder parents) and well-formed strings hold on the
examples, and the table above lists exactly the schema's message types
with the right direction.

That validator is a self-test, not the runtimes' validator. Real
validation happens in each runtime's own contract tests: the daemon's
Pydantic models and the extension's zod schemas MUST accept every file
in `examples/valid/` and reject every file in `examples/invalid/`.

## Changing the contract

The contract is a versioned schema artifact (design, Key Decisions).
A change to any message shape bumps `CONTRACT_VERSION` and the `v` const
in the schema, lands in a new `v<N>/` directory beside this one, and
keeps `hello`, `hello.result` and `error` byte-for-byte compatible.
