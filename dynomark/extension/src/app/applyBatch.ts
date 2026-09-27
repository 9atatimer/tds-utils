// applyBatch.ts -- use case "A batch is applied" (design, Behaviors and
// Interfaces): apply_batch(batch, *, tree) -> BatchReceipt. Reads the tree
// first (the receipt's snapshot), then runs the operations in order through
// BookmarkTreePort (contract v1 README, "Write batches").
//
// Beyond the design's signature, the use case takes the connection's
// `hello.result` values it cannot apply without (the owned roots, whose
// graveyard every remove targets, and the host id) and the clock that stamps
// the snapshot.

import {
  appliedReceipt,
  freshCursor,
  hasChangedTree,
  partialReceipt,
  withFailed,
  withOutcome,
  withStarted,
  type BatchCursor,
  type BatchReceipt,
  type OpFailed,
  type OpOutcome,
  type Operation,
  type WriteBatch,
} from '../domain/batch.js';
import { existingBookmark, existingFolder } from '../domain/ops.js';
import { toSnapshot } from '../domain/snapshot.js';
import type { FolderPath, OwnedRoots, SnapshotNode } from '../domain/tree.js';
import type { BatchId, HostId, NodeId } from '../domain/values.js';
import { MAX_DETAIL, fitText } from '../domain/limits.js';
import { BrowserRefused, type BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { Clock } from '../ports/clock.js';
import type { StoragePort } from '../ports/storage.js';

// --- Types ---

/** What the connection's hello.result told the extension, and every batch is applied against. */
export interface BatchContext {
  readonly owned_roots: OwnedRoots;
  readonly host_id: HostId;
}

export interface ApplyDeps {
  readonly tree: BookmarkTreePort;
  readonly storage: StoragePort;
  readonly clock: Clock;
}

/** The one durable cursor names another batch: no other batch starts until that one's receipt is acknowledged. */
export class CursorHeld extends Error {
  readonly held: BatchId;

  constructor(held: BatchId, offered: BatchId) {
    super(`cursor held by batch ${held}; batch ${offered} must wait for its receipt result`);
    this.name = 'CursorHeld';
    this.held = held;
  }
}

// --- Pure helpers ---

/** The folder an op writes into: its parent, its destination, or the graveyard. */
function targetOf(op: Operation, roots: OwnedRoots): FolderPath {
  switch (op.op) {
    case 'create_folder':
    case 'create':
      return op.parent;
    case 'move':
      return op.to;
    case 'remove':
      return roots.graveyard;
  }
}

// --- Flow ---

async function call(op: Operation, target: NodeId, tree: BookmarkTreePort): Promise<SnapshotNode> {
  switch (op.op) {
    case 'create_folder':
      return tree.createFolder(target, op.title);
    case 'create':
      return tree.createBookmark(target, op.title, op.url);
    case 'move':
    case 'remove':
      return tree.move(op.node_id, target);
  }
}

/** The op's post-condition: the node it would have produced or moved, when that already holds. */
async function postCondition(op: Operation, target: NodeId, tree: BookmarkTreePort): Promise<NodeId | undefined> {
  if (op.op === 'create_folder') return existingFolder(await tree.getChildren(target), target, op.title)?.id;
  if (op.op === 'create') return existingBookmark(await tree.getChildren(target), target, op.url)?.id;
  return (await tree.getNode(op.node_id))?.parent_id === target ? op.node_id : undefined;
}

/** Where one op leaves the batch: the cursor with its outcome recorded, or the reason it failed. */
type Step = { readonly cursor: BatchCursor } | { readonly failed: OpFailed };

/** Run one op under the cursor: mark it started, make the browser call, record the outcome. */
async function stepOp(op: Operation, cursor: BatchCursor, context: BatchContext, deps: ApplyDeps): Promise<Step> {
  const target = await deps.tree.resolveFolder(targetOf(op, context.owned_roots));
  if (target === undefined) return { failed: { index: op.index, reason: 'parent_missing' } };
  if (cursor.started === op.index) {
    const done = await postCondition(op, target, deps.tree);
    if (done !== undefined) return { cursor: await record(cursor, applied(op, done), deps.storage) };
  }
  await deps.storage.saveCursor(withStarted(cursor, op.index));
  try {
    const node = await call(op, target, deps.tree);
    return { cursor: await record(cursor, applied(op, node.id), deps.storage) };
  } catch (error) {
    if (!(error instanceof BrowserRefused)) throw error;
    return { failed: { index: op.index, reason: 'browser_error', detail: fitText(error.message, MAX_DETAIL).text } };
  }
}

function applied(op: Operation, node_id: NodeId): OpOutcome {
  return { outcome: 'applied', index: op.index, node_id, changed: true };
}

async function record(cursor: BatchCursor, outcome: OpOutcome, storage: StoragePort): Promise<BatchCursor> {
  const next = withOutcome(cursor, outcome);
  await storage.saveCursor(next);
  return next;
}

/**
 * Apply one offered batch and answer it with a receipt. Resumes from the
 * durable cursor when it names this batch; recorded ops are reported, never
 * repeated. The cursor stays until the receipt's result is acknowledged.
 */
export async function applyBatch(batch: WriteBatch, context: BatchContext, deps: ApplyDeps): Promise<BatchReceipt> {
  const held = await deps.storage.loadCursor();
  if (held !== undefined && held.batch_id !== batch.batch_id) throw new CursorHeld(held.batch_id, batch.batch_id);
  const snapshot = toSnapshot(await deps.tree.readTree(), deps.clock.now());
  let cursor = held ?? freshCursor(batch.batch_id);
  const pre_batch = !hasChangedTree(cursor);
  if (held === undefined) await deps.storage.saveCursor(cursor);
  for (const op of batch.operations.slice(cursor.next_index)) {
    const step = await stepOp(op, cursor, context, deps);
    if ('failed' in step) {
      await deps.storage.saveCursor(withFailed(cursor, step.failed));
      return partialReceipt(batch.batch_id, cursor.outcomes, step.failed, snapshot, pre_batch);
    }
    cursor = step.cursor;
  }
  return appliedReceipt(batch.batch_id, cursor.outcomes, snapshot, pre_batch);
}
