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
`minProperties`, `oneOf`, `anyOf`, `allOf`, `not`, `if`/`then`. Every
`pattern` is anchored `^...$` and uses only character classes and
counted repetition, so ECMA-262, Python `re` and Rust `regex` read it the
same way.

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
- Size limits are on the JSON byte length:
  - daemon -> extension: at most 1 MiB (1,048,576 bytes), Chrome's limit
    for a message from a native host. Everything that can grow is
    paginated (`index.pull`, `search`, `diff.page`, `outline.get`).
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

## Endpoint

- The daemon listens on the unix socket `$DYNOMARK_SOCKET` when set,
  else `${XDG_STATE_HOME:-$HOME/.local/state}/dynomark/daemon.sock`. The
  directory is mode 0700, the socket 0600. No TCP port exists.
- The native-messaging host name is `tds.dynomark`. The browser starts
  the shim; the shim connects to the socket and pipes.
- One extension connection at a time: a connection whose `hello` succeeds
  supersedes any earlier one, which the daemon closes.

## Envelope

Every message is a flat JSON object with these envelope fields plus its
own body fields:

| Field | Type | On | Meaning |
|---|---|---|---|
| `v` | integer | every message | The sender's contract version. Pinned to `1` in every message except the three frozen ones (`hello`, `hello.result`, `error`), which accept any `v >= 1` |
| `type` | string | every message | The message type; the discriminator |
| `id` | `Id` | requests | Caller-chosen request id (extension side). A retry of the same request reuses the same `id` and body |
| `re` | `Id` | responses | The `id` of the request this answers (`error` only: `null` when unreadable) |
| `event_id` | `Id` | events | Daemon-chosen, unique in the daemon's store, never reused; durable until acknowledged |

A message has exactly one of `id`, `re`, `event_id`, and that fixes its
direction: requests go extension -> daemon; responses and events go
daemon -> extension. The daemon never sends a request; the extension
never sends a response or an event.

Every request `X` is answered by exactly one frame: `X.result` or
`error`, with `re` = the request's `id`. Responses may arrive in any
order relative to other requests' responses, and events interleave
freely.

Frozen messages: `hello`, `hello.result` and `error` keep their v1 shape
in every future version, so any two versions can always complete the
handshake and read an error.

Conventions: optional fields are omitted, never `null`; `null` appears
only where the schema says `null` (end of pagination, the browser root's
`parent_id`, an unaccepted `DiffItem`, an `undo` that dropped
everything, an unreadable `re`). Times are `EpochMs`. Ids are opaque:
compare byte-for-byte, never parse.

## Connection lifecycle

1. The extension connects and sends `hello` with its `v` and the
   `Follow Up` folder it resolved (zero folders named `Follow Up`:
   create one under the bookmarks bar first; several: use the one under
   the bookmarks bar).
2. The daemon answers `hello.result` with its own `v`, `host_id`,
   `role`, `owned_roots`, and `mode`:

   | Versions | `mode` | What continues |
   |---|---|---|
   | equal | `full` | everything |
   | extension newer than daemon | `read_only` | the read-only set only, spoken at the daemon's version |
   | extension older than daemon | `refused` | nothing but `hello` |

   Read-only set: `hello`, `status`, `events.replay`, `events.ack`,
   `index.pull`, `search`, `ask`, `placement.explain`. In `read_only` the
   daemon sends no `batch.offer`; any other request is answered `error`
   `version_mismatch`. In `refused`, every request but `hello` is.
3. Any request before a `hello` has been answered gets `error`
   `hello_required`. A second `hello` on a connection is answered again
   and changes nothing else. A non-frozen message whose `v` is not the
   daemon's version gets `error` `version_mismatch`.
4. In `full` mode the extension then sends `tree.snapshot` and
   `events.replay`, and pulls the index (`index.pull` from the first
   page). The daemon sends no event before it has answered `hello`, and
   may push live events at any time after.
5. Because `ingest` is idempotent, the extension MAY re-send `ingest`
   for every node currently in `Follow Up` after a `full` hello; the
   daemon treats repeats as no-ops.

## Message table

| Message type | Direction | Purpose | Design use case |
|---|---|---|---|
| `hello` | extension -> daemon | Open the connection: extension's contract version and resolved `Follow Up` | Transport contract: identity and version |
| `hello.result` | daemon -> extension | Daemon's version, host id, `HostRole`, `OwnedRoots`, connection mode | Transport contract: identity and version; One writer (Goal 7) |
| `ingest` | extension -> daemon | Submit a save with its raw URL, optional `Capture`, backfill flag | A save is submitted; A save is ingested; Content is captured from the open tab; Open Question 3 (backfill) |
| `ingest.result` | daemon -> extension | The `Job` for the save (the existing one on a repeat) | A save is ingested; A duplicate identity is parked |
| `job.retry` | extension -> daemon | User retry of a `FAILED` job | State Machine: FAILED -> QUEUED |
| `job.retry.result` | daemon -> extension | The job after the retry | State Machine: FAILED -> QUEUED |
| `job.updated` | daemon -> extension | Event: a job changed state | Transport contract: direction (job finished); A failed enrichment is retried, then parked |
| `tree.snapshot` | extension -> daemon | The full tree, on connect and after owned-root changes (debounced) | An entry is placed (outline source); A diff is proposed; Writer marker |
| `tree.snapshot.result` | daemon -> extension | Snapshot recorded | An entry is placed |
| `move.observed` | extension -> daemon | A move between owned folders, with `origin` user or extension | A user move becomes feedback |
| `move.observed.result` | daemon -> extension | Move recorded or discarded | A user move becomes feedback |
| `batch.offer` | daemon -> extension | Event: a `WriteBatch` to apply | A placement becomes a batch; Transport contract: partial failure (re-offer) |
| `batch.receipt` | extension -> daemon | `BatchReceipt` (`APPLIED` / `PARTIAL` / `REJECTED`) with the pre-batch snapshot | A batch is applied; A batch resumes after termination; A batch fails midway; A receipt is delivered |
| `batch.receipt.result` | daemon -> extension | Receipt recorded (once per batch) | A receipt is delivered; A receipt is processed |
| `events.replay` | extension -> daemon | Re-send every unacknowledged event | Transport contract: delivery |
| `events.replay.result` | daemon -> extension | Sent after the replayed events; how many | Transport contract: delivery |
| `events.ack` | extension -> daemon | Acknowledge `job.updated` events | Transport contract: delivery |
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
| `diff.page` | extension -> daemon | Read one page of a diff's items | A diff is proposed |
| `diff.page.result` | daemon -> extension | One page of `DiffItem`s | A diff is proposed |
| `diff.accept` | extension -> daemon | Accept one `DiffItem` (item id only) | A diff item is accepted; An audit item may cross the boundary |
| `diff.accept.result` | daemon -> extension | Recorded `accepted_at` and the batch it produced | A diff item is accepted |
| `outline.get` | extension -> daemon | Read one page of the owned `TreeOutline` | Glossary: `pinned`, `locked` (settings view) |
| `outline.get.result` | daemon -> extension | One page of `OutlineFolder`s | Glossary: `pinned`, `locked` |
| `folder.flags.set` | extension -> daemon | Set `pinned` / `locked` on an owned folder | Placement respects a lock; pinned folders immune to diffs |
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
  (below), so a repeat is harmless.
- **Events are durable until acknowledged.** A `job.updated` is
  acknowledged by `events.ack`; a `batch.offer` only by a `batch.receipt`
  for its `batch.batch_id` (an `events.ack` naming it is ignored for that
  id). Unknown and already-acknowledged ids in `events.ack` are ignored.
- **Replay.** `events.replay` makes the daemon re-send every
  unacknowledged event, oldest first, as ordinary event frames, then
  answer `events.replay.result` with the count. The daemon may also
  re-push an unacknowledged event at any time. The extension
  de-duplicates by `event_id` and handles every event idempotently.
- **Index freshness.** The extension re-pulls the whole `LocalIndex`
  (from the first page) after a `full` hello and after any `job.updated`
  whose state is `FILED` or `INDEXED`; it swaps the new index in only
  when the last page (`next_cursor` null) arrives.
- **Pagination.** A cursor is opaque and valid only for the message type
  that minted it. When the underlying data changes between pages the
  daemon MAY answer `error` `stale_cursor`; the extension restarts from
  the first page. `limit` is an upper bound; the daemon returns fewer
  rows whenever needed to keep the frame within 1 MiB. `search` repeats
  its `query` on every page.

| Request | Idempotency key | A repeat... |
|---|---|---|
| `ingest` | (`bookmark.node_id`, identity of `bookmark.url`) | returns the same job; nothing new is queued |
| `job.retry` | `job_id` | on a job not `FAILED`, changes nothing |
| `tree.snapshot` | `snapshot.taken_at` | the daemon keeps the snapshot with the latest `taken_at` |
| `move.observed` | (`move.node_id`, `move.observed_at`) | records nothing new |
| `batch.receipt` | `receipt.batch_id` | records nothing new; the first receipt recorded wins |
| `events.ack` | each event id | is a no-op |
| `undo` | `batch_id` | returns the same inverse batch; at most one inverse per batch |
| `diff.propose` | request `id` | with the same `id` returns the same diff; a new `id` proposes a new one |
| `diff.accept` | `item_id` | returns the same `accepted_at` and batch |
| `folder.flags.set` | (`path`, flag values) | sets the same values |
| all others | none needed | are read-only |

## Write batches

The daemon never touches the tree; the extension applies `WriteBatch`es
offered by `batch.offer`, one batch at a time, in the order offered.

**Paths.** A `FolderPath` is `{root, names}`: `root` is a `RootKey`
(`bar`, `other`, `mobile`, `menu`), mapped to the browser's top-level
folders by the extension (Chrome: bookmarks bar / other / mobile;
Firefox: toolbar / unfiled / mobile / menu), and `names` are folder
titles downward. Resolution picks, at each level, the child *folder*
with the lowest index whose title equals the name exactly. `names: []`
is the top-level folder itself.

**Operations** (each carries `index`, and `batch.operations[i].index ==
i`):

| `op` | Fields | Applies as | Node id in the receipt |
|---|---|---|---|
| `create_folder` | `parent`, `title` | create folder `title` in `parent` unless a child folder with that exact title exists; `parent` must exist | the folder |
| `create` | `parent`, `title`, `url` | create a bookmark in `parent` unless a child bookmark with that exact `url` exists; `parent` must exist | the bookmark |
| `move` | `node_id`, `to`, `expect`? | move the node to the end of `to` unless it is already directly in `to`; `to` must exist | `node_id` |
| `remove` | `node_id`, `expect`? | move the node to the end of `owned_roots.graveyard` (this connection's `hello.result`) unless already directly in it; never deletes | `node_id` |

**Preconditions.** `move` and `remove` may carry `expect`: `parent_path`
(the node is directly in the folder that path resolves to), `parent_id`
(its parent node id), `empty: true` (it is a folder with no children).
The extension checks every present clause immediately before the op. If
any fails, or the node no longer exists, the op is **skipped** -- listed
in `skipped` with a `SkipReason` -- and the batch continues. This is how
a guarded undo re-checks itself at apply time. An op without `expect`
whose node is missing, or any op whose target folder does not resolve,
**fails**: the batch stops and the receipt is `PARTIAL`.

**Boundary.** Before the first op, the extension checks every op against
`owned_roots`: the target folder (`parent`, `to`, the graveyard) and,
for `move`/`remove`, the node's current parent must be the `follow_up`,
`dynomark` or `graveyard` root or inside one, unless the batch carries
`diff_item_id`. If any op fails the check the batch is `REJECTED`
(`boundary`) and nothing is touched. A batch whose op indices are not
`0..n-1` is `REJECTED` (`invalid`).

**Cursor and resume.** After each op the extension records (`batch_id`,
next op index) in extension storage. When the same batch is offered
again it resumes from the cursor without repeating earlier ops; a batch
already fully applied is answered `APPLIED` again without touching the
tree. Outcomes of ops before a restart are re-derived: `create_folder`
and `create` by resolving their path, `move`/`remove` as `applied` when
the node is directly in the target folder, otherwise `skipped` with
`unknown_after_resume`.

**Receipts.** `batch.receipt` carries a `BatchReceipt` discriminated by
`state`:

- `APPLIED`: `applied` (index + node id) and `skipped` (index + reason)
  partition all op indices, each list ascending.
- `PARTIAL`: `applied` and `skipped` partition `0..failed.index-1`;
  `failed` names the op that failed and why; later ops were not tried.
- `REJECTED`: `reason` (`boundary` or `invalid`); nothing was touched.

Every receipt carries `snapshot`: the full tree read immediately before
this apply attempt touched the tree (for a resumed or already-applied
batch, read at the start of this attempt). Moves the extension observes
while applying a batch, of nodes that batch's ops name, are reported
with `origin: extension`.

## Writer marker (MVP)

A writer daemon keeps a marker folder in the owned tree: an empty folder
titled exactly `dynomark-writer:<host_id>` directly in
`owned_roots.dynomark`, created by an ordinary `batch.offer`. The daemon
reads markers from the latest `tree.snapshot`. A writer that sees
another host's marker is in conflict: it offers no batches, answers
`undo`, `diff.accept` and `folder.flags.set` with `error`
`writer_conflict`, still accepts `ingest` (the job indexes, then ends
`FAILED` with a `last_error` naming the conflict), and reports it in
`writer.status.result`. Marker folders are excluded from the
`TreeOutline` and from placement. Clearing a stale marker is a user edit
in the tree.

## Roles and errors

| Code | Sent when | Retry |
|---|---|---|
| `version_mismatch` | a non-frozen message's `v` is not the daemon's; a request outside the connection's `mode` | no |
| `hello_required` | a request before `hello` was answered | after `hello` |
| `not_writer` | `undo`, `diff.accept` or `folder.flags.set` on a `reader` host | no |
| `writer_conflict` | the same three on a writer that sees another host's marker | no |
| `not_found` | an unknown `job_id`, `batch_id`, `diff_id`, `item_id`, identity, url or folder path | no |
| `invalid` | a body that fails the schema, or a valid body the daemon cannot act on (e.g. `undo` of a batch that is not `APPLIED`, `folder.flags.set` outside the owned roots) | no |
| `stale_cursor` | a cursor from before a data change | restart from page 1 |
| `busy` | temporarily unable (e.g. a model loading) | yes, same `id`, after backoff |
| `internal` | anything unexpected | yes, same `id`, after backoff |

A `reader` host answers `not_writer` only to the three requests above
and serves every other one: `ingest` indexes for its own search and chat
and never files (the job ends `INDEXED`), `move.observed` is discarded
for feedback, and no `batch.offer` is ever sent.

## Size limits

| What | Limit |
|---|---|
| Frame, daemon -> extension | 1 MiB of JSON |
| Frame, extension -> daemon | 32 MiB of JSON |
| `LocalIndexRow` | 512 bytes, measured as the UTF-8 length of the row serialized as compact JSON (no whitespace, non-ASCII unescaped); the daemon trims `summary`, then `tags`, then `title`, and leaves out a row whose `identity` alone cannot fit |
| `Capture.text` | 1,048,576 code points |
| Titles (`Title`) | 4,096 code points (snapshot titles and urls are uncapped: the snapshot is the tree as it is) |
| `Url`, `Identity` | 65,536 code points |
| `search.query` | 1 to 1,024 code points |
| `ask.question` | 1 to 8,192 code points; `history` at most 50 turns |
| Operations per batch | 1 to 1,000; per `DiffItem`, 1 to 100 |
| Page sizes | `index.pull`, `outline.get`: 1,000; `search`, `diff.page`: 100 |
| `events.ack` | 1 to 1,000 ids |
| Ids | `Id` 1 to 128 of `[A-Za-z0-9._:-]`; `NodeId` 1 to 64 of `[A-Za-z0-9._-]`; `HostId` 1 to 64, alphanumeric first; `Cursor` 1 to 1,024 printable ASCII, no space |

The schema caps are upper bounds; they do not guarantee a daemon ->
extension frame fits 1 MiB. The daemon MUST NOT send a frame over the
limit: it shortens pages, and a batch it cannot fit is not offered (its
job fails with a `last_error` saying so).

## Validation

`python3 dynomark/contract/check.py` checks this directory against
itself with the Python standard library only (no `jsonschema`; it is not
on the tech radar): every message type has a valid example, every
example is valid JSON of a known type, every valid example passes and
every invalid example fails a small built-in validator for the keyword
subset above (for the reason `invalid-rules.json` names), op indices,
receipt partitions and 512-byte rows hold on the examples, and the table
above lists exactly the schema's message types with the right direction.

That validator is a self-test, not the runtimes' validator. Real
validation happens in each runtime's own contract tests: the daemon's
Pydantic models and the extension's zod schemas MUST accept every file
in `examples/valid/` and reject every file in `examples/invalid/`.

## Changing the contract

The contract is a versioned schema artifact (design, Key Decisions).
A change to any message shape bumps `CONTRACT_VERSION` and the `v` const
in the schema, lands in a new `v<N>/` directory beside this one, and
keeps `hello`, `hello.result` and `error` byte-for-byte compatible.
