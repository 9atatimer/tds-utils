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
  type OpMove,
  type OpRemove,
  type Operation,
  type SkipReason,
  type WriteBatch,
} from '../domain/batch.js';
import { existingBookmark, existingFolder, expectFailure } from '../domain/ops.js';
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

// --- Types (the flow's own) ---

/** What to do with one op, decided by reading the tree only. */
type Decision =
  | { readonly kind: 'noop'; readonly node_id: NodeId }
  | { readonly kind: 'skip'; readonly reason: SkipReason }
  | { readonly kind: 'fail' }
  | { readonly kind: 'run'; readonly target: NodeId };

/** Where one op leaves the batch: the cursor with its outcome recorded, or the reason it failed. */
type Step = { readonly cursor: BatchCursor } | { readonly failed: OpFailed };

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

function applied(op: Operation, node_id: NodeId, changed: boolean): OpOutcome {
  return { outcome: 'applied', index: op.index, node_id, changed };
}

// --- Flow: reading the tree ---

/** The op's post-condition: the node it would have produced or moved, when that already holds. */
async function postCondition(op: Operation, target: NodeId, tree: BookmarkTreePort): Promise<NodeId | undefined> {
  if (op.op === 'create_folder') return existingFolder(await tree.getChildren(target), target, op.title)?.id;
  if (op.op === 'create') return existingBookmark(await tree.getChildren(target), target, op.url)?.id;
  return (await tree.getNode(op.node_id))?.parent_id === target ? op.node_id : undefined;
}

async function decideCreate(
  op: Operation & { readonly op: 'create_folder' | 'create' },
  target: NodeId | undefined,
  tree: BookmarkTreePort,
): Promise<Decision> {
  if (target === undefined) return { kind: 'fail' };
  const children = await tree.getChildren(target);
  const existing = op.op === 'create_folder' ? existingFolder(children, target, op.title) : existingBookmark(children, target, op.url);
  return existing === undefined ? { kind: 'run', target } : { kind: 'noop', node_id: existing.id };
}

/** Already there: a no-op, expect unread. Else every expect clause, then the target (contract v1, Preconditions). */
async function decideMove(op: OpMove | OpRemove, target: NodeId | undefined, tree: BookmarkTreePort): Promise<Decision> {
  const node = await tree.getNode(op.node_id);
  if (node === undefined) return { kind: 'skip', reason: 'node_missing' };
  if (target !== undefined && node.parent_id === target) return { kind: 'noop', node_id: node.id };
  const children = node.kind === 'folder' ? await tree.getChildren(node.id) : [];
  const parent_path_id = op.expect.parent_path === undefined ? undefined : await tree.resolveFolder(op.expect.parent_path);
  const reason = expectFailure(op.expect, {
    parent_id: node.parent_id,
    parent_path_id,
    is_folder: node.kind === 'folder',
    child_count: children.length,
  });
  if (reason !== undefined) return { kind: 'skip', reason };
  return target === undefined ? { kind: 'fail' } : { kind: 'run', target };
}

/** Decide an op without touching the tree (contract v1, Cursor and resume, step 1). */
async function decide(op: Operation, context: BatchContext, tree: BookmarkTreePort): Promise<Decision> {
  const target = await tree.resolveFolder(targetOf(op, context.owned_roots));
  return op.op === 'create_folder' || op.op === 'create' ? decideCreate(op, target, tree) : decideMove(op, target, tree);
}

// --- Flow: writing ---

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

async function record(cursor: BatchCursor, outcome: OpOutcome, storage: StoragePort): Promise<BatchCursor> {
  const next = withOutcome(cursor, outcome);
  await storage.saveCursor(next);
  return next;
}

/** Mark the op started (durably), make the browser call, record the outcome; a refusal fails the op. */
async function runOp(op: Operation, target: NodeId, cursor: BatchCursor, deps: ApplyDeps): Promise<Step> {
  await deps.storage.saveCursor(withStarted(cursor, op.index));
  try {
    const node = await call(op, target, deps.tree);
    return { cursor: await record(cursor, applied(op, node.id, true), deps.storage) };
  } catch (error) {
    if (!(error instanceof BrowserRefused)) throw error;
    return { failed: { index: op.index, reason: 'browser_error', detail: fitText(error.message, MAX_DETAIL).text } };
  }
}

/** One op under the cursor: a started op whose post-condition holds is applied; a no-op or skip is recorded; else it runs. */
async function stepOp(op: Operation, cursor: BatchCursor, context: BatchContext, deps: ApplyDeps): Promise<Step> {
  if (cursor.started === op.index) {
    const target = await deps.tree.resolveFolder(targetOf(op, context.owned_roots));
    const done = target === undefined ? undefined : await postCondition(op, target, deps.tree);
    if (done !== undefined) return { cursor: await record(cursor, applied(op, done, true), deps.storage) };
  }
  const decision = await decide(op, context, deps.tree);
  switch (decision.kind) {
    case 'noop':
      return { cursor: await record(cursor, applied(op, decision.node_id, false), deps.storage) };
    case 'skip':
      return { cursor: await record(cursor, { outcome: 'skipped', index: op.index, reason: decision.reason }, deps.storage) };
    case 'fail':
      return { failed: { index: op.index, reason: 'parent_missing' } };
    case 'run':
      return runOp(op, decision.target, cursor, deps);
  }
}

// --- Entry: the use case ---

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
