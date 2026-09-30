// diffs.ts -- the extension half of TreeDiffs (design, "Diffs": propose_diff
// of kind audit or rebuild; nothing is applied until a DiffItem is accepted,
// and each acceptance is its own batch; Non-Goals: suggest-only, one accepted
// item at a time; glossary `pinned`, `locked`). The diff view is a page; these
// are the requests the background makes for it. Merge rules are the daemon's
// and undefined for v1 (design, Open Question 1).

import type { DiffItem, DiffKind, OutlineFolder, TreeDiff } from '../domain/diff.js';
import type { FolderPath } from '../domain/tree.js';
import type { BatchId, Cursor, EpochMs, Id, NodeId } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { Clock } from '../ports/clock.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';
import { sendTreeSnapshot } from './onConnected.js';

// --- Types ---

interface Talk {
  readonly transport: TransportPort;
  readonly ids: IdSource;
}

/** One page of something the daemon paginates. */
export interface Paged {
  readonly next_cursor: Cursor | null;
}

/** What the daemon recorded when it accepted an item: when, and the batch that realizes it. */
export interface Acceptance {
  readonly item_id: Id;
  readonly accepted_at: EpochMs;
  readonly batch_id: BatchId;
}

/** The flags to change on a folder; at least one. */
export interface FolderFlags {
  readonly pinned?: boolean;
  readonly locked?: boolean;
}

/** Another item's acceptance is still in flight: audit is one accepted item at a time. */
export class AcceptPending extends Error {
  constructor(pending: Id) {
    super(`one diff item at a time: ${pending} is still being accepted`);
    this.name = 'AcceptPending';
  }
}

// --- Pure helpers ---

function cursorField(cursor: Cursor | undefined): { readonly cursor?: Cursor } {
  return cursor === undefined ? {} : { cursor };
}

// --- Flow ---

/** Send the tree as read now and await its result, then propose a diff (so an audit compares against the current bar). */
export async function proposeDiff(
  kind: DiffKind,
  deps: Talk & { readonly tree: BookmarkTreePort; readonly clock: Clock },
): Promise<TreeDiff> {
  await sendTreeSnapshot(deps);
  return resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'diff.propose', id: deps.ids.next(), kind })).diff;
}

/** One page of diff headers, newest first. */
export async function listDiffs(cursor: Cursor | undefined, deps: Talk): Promise<Paged & { readonly diffs: readonly TreeDiff[] }> {
  const r = resultOrThrow(
    await deps.transport.send({ v: CONTRACT_VERSION, type: 'diff.list', id: deps.ids.next(), ...cursorField(cursor) }),
  );
  return { diffs: r.diffs, next_cursor: r.next_cursor };
}

/** One page of a diff's items; an accepted item names its batch and that batch's state. */
export async function readDiffPage(
  diff_id: Id,
  cursor: Cursor | undefined,
  deps: Talk,
): Promise<Paged & { readonly diff: TreeDiff; readonly items: readonly DiffItem[] }> {
  const frame = { v: CONTRACT_VERSION, type: 'diff.page', id: deps.ids.next(), diff_id, ...cursorField(cursor) } as const;
  const r = resultOrThrow(await deps.transport.send(frame));
  return { diff: r.diff, items: r.items, next_cursor: r.next_cursor };
}

/** One page of the owned outline with its pin and lock flags. */
export async function readOutline(cursor: Cursor | undefined, deps: Talk): Promise<Paged & { readonly folders: readonly OutlineFolder[] }> {
  const r = resultOrThrow(
    await deps.transport.send({ v: CONTRACT_VERSION, type: 'outline.get', id: deps.ids.next(), ...cursorField(cursor) }),
  );
  return { folders: r.outline, next_cursor: r.next_cursor };
}

/** Pin or lock an owned folder, naming its node id and the path it was shown at (the daemon checks they still match). */
export async function setFolderFlags(
  folder: { readonly node_id: NodeId; readonly path: FolderPath },
  flags: FolderFlags,
  deps: Talk,
): Promise<OutlineFolder> {
  if (flags.pinned === undefined && flags.locked === undefined) throw new Error('folder.flags.set changes at least one flag');
  const frame = {
    v: CONTRACT_VERSION,
    type: 'folder.flags.set',
    id: deps.ids.next(),
    node_id: folder.node_id,
    path: folder.path,
    ...(flags.pinned === undefined ? {} : { pinned: flags.pinned }),
    ...(flags.locked === undefined ? {} : { locked: flags.locked }),
  } as const;
  return resultOrThrow(await deps.transport.send(frame)).folder;
}

// --- Acceptance, one item at a time ---

export class DiffAcceptance {
  private pending: Id | undefined;

  /** Accept one item by id; refused while another item's acceptance is in flight. */
  async accept(item_id: Id, deps: Talk): Promise<Acceptance> {
    if (this.pending !== undefined) throw new AcceptPending(this.pending);
    this.pending = item_id;
    try {
      const r = resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'diff.accept', id: deps.ids.next(), item_id }));
      return { item_id: r.item_id, accepted_at: r.accepted_at, batch_id: r.batch_id };
    } finally {
      this.pending = undefined;
    }
  }
}
