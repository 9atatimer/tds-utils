// applyBatch.ts -- use case "A batch is applied" (design, Behaviors and
// Interfaces): apply_batch(batch, *, tree) -> BatchReceipt. Reads the tree
// first (the receipt's snapshot), then runs the operations in order through
// BookmarkTreePort (contract v1 README, "Write batches").
//
// Beyond the design's signature, the use case takes the connection's
// `hello.result` values it cannot apply without (the owned roots, whose
// graveyard every remove targets, and the host id) and the clock that stamps
// the snapshot.

import { appliedReceipt, type BatchReceipt, type OpOutcome, type Operation, type WriteBatch } from '../domain/batch.js';
import { toSnapshot } from '../domain/snapshot.js';
import type { FolderPath, OwnedRoots, SnapshotNode } from '../domain/tree.js';
import type { HostId, NodeId } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { Clock } from '../ports/clock.js';

// --- Types ---

/** What the connection's hello.result told the extension, and every batch is applied against. */
export interface BatchContext {
  readonly owned_roots: OwnedRoots;
  readonly host_id: HostId;
}

export interface ApplyDeps {
  readonly tree: BookmarkTreePort;
  readonly clock: Clock;
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

async function runOp(op: Operation, context: BatchContext, tree: BookmarkTreePort): Promise<OpOutcome> {
  const target = await tree.resolveFolder(targetOf(op, context.owned_roots));
  if (target === undefined) throw new Error(`op ${op.index}: target folder does not resolve`);
  const node = await call(op, target, tree);
  return { outcome: 'applied', index: op.index, node_id: node.id, changed: true };
}

/** Apply one offered batch and answer it with a receipt. */
export async function applyBatch(batch: WriteBatch, context: BatchContext, deps: ApplyDeps): Promise<BatchReceipt> {
  const snapshot = toSnapshot(await deps.tree.readTree(), deps.clock.now());
  const outcomes: OpOutcome[] = [];
  for (const op of batch.operations) outcomes.push(await runOp(op, context, deps.tree));
  return appliedReceipt(batch.batch_id, outcomes, snapshot, true);
}
