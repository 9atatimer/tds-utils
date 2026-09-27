// batch.ts -- write batches, their receipts and the in-flight cursor (design,
// "Operation", "WriteBatch", "BatchReceipt"; contract v1, "Write batches").

import type { FolderPath, Snapshot } from './tree.js';
import type { BatchId, Id, NodeId, Title, Url } from './values.js';

// --- Operations ---

/** Preconditions a move or remove checks before it touches the tree. */
export interface Expect {
  readonly parent_id: NodeId;
  readonly parent_path?: FolderPath;
  readonly empty?: true;
}

/** Create folder `title` in `parent` unless a child folder with that exact title exists. */
export interface OpCreateFolder {
  readonly op: 'create_folder';
  readonly index: number;
  readonly parent: FolderPath;
  readonly title: Title;
}

/** Create a bookmark in `parent` unless a child bookmark with that exact url exists. */
export interface OpCreate {
  readonly op: 'create';
  readonly index: number;
  readonly parent: FolderPath;
  readonly title: Title;
  readonly url: Url;
}

/** Move the node to the end of `to` unless it is already directly in `to`. */
export interface OpMove {
  readonly op: 'move';
  readonly index: number;
  readonly node_id: NodeId;
  readonly to: FolderPath;
  readonly expect: Expect;
}

/** Move the node to the end of the graveyard; never deletes. */
export interface OpRemove {
  readonly op: 'remove';
  readonly index: number;
  readonly node_id: NodeId;
  readonly expect: Expect;
}

/** One path-idempotent step of a batch. There is no hard delete. */
export type Operation = OpCreateFolder | OpCreate | OpMove | OpRemove;

/** Ordered operations offered by the daemon; an optional accepted `DiffItem` reference exempts it from the boundary. */
export interface WriteBatch {
  readonly batch_id: BatchId;
  readonly operations: readonly Operation[];
  readonly diff_item_id?: Id;
}

// --- Receipts ---

export type SkipReason = 'node_missing' | 'parent_mismatch' | 'not_empty';
export type FailReason = 'parent_missing' | 'browser_error';
export type RejectReason = 'boundary' | 'invalid' | 'writer_conflict';
export type ReceiptState = 'APPLIED' | 'PARTIAL' | 'REJECTED';
export type BatchState = 'PROPOSED' | ReceiptState;

export interface OpApplied {
  readonly index: number;
  readonly node_id: NodeId;
  /** False when the op was already satisfied (path-idempotent no-op). */
  readonly changed: boolean;
}

export interface OpSkipped {
  readonly index: number;
  readonly reason: SkipReason;
}

export interface OpFailed {
  readonly index: number;
  readonly reason: FailReason;
  readonly detail?: string;
}

interface ReceiptBase {
  readonly batch_id: BatchId;
  /** The full tree read at the start of this apply attempt; absent only when `snapshot_omitted`. */
  readonly snapshot?: Snapshot;
  readonly snapshot_omitted?: true;
  /** True only when no op of this batch had changed the tree before the snapshot was read. */
  readonly pre_batch: boolean;
}

export interface ReceiptApplied extends ReceiptBase {
  readonly state: 'APPLIED';
  readonly applied: readonly OpApplied[];
  readonly skipped: readonly OpSkipped[];
}

export interface ReceiptPartial extends ReceiptBase {
  readonly state: 'PARTIAL';
  readonly applied: readonly OpApplied[];
  readonly skipped: readonly OpSkipped[];
  readonly failed: OpFailed;
}

export interface ReceiptRejected extends ReceiptBase {
  readonly state: 'REJECTED';
  readonly reason: RejectReason;
  readonly detail?: string;
}

/** The extension's answer for a batch: APPLIED, PARTIAL with the applied prefix, or REJECTED with a reason. */
export type BatchReceipt = ReceiptApplied | ReceiptPartial | ReceiptRejected;

// --- Cursor ---

/** The recorded outcome of one op of the in-flight batch. */
export type OpOutcome = ({ readonly outcome: 'applied' } & OpApplied) | ({ readonly outcome: 'skipped' } & OpSkipped);

/**
 * The in-flight batch cursor: durable extension state that survives a
 * service-worker restart. `outcomes` covers ops 0..next_index-1 in order;
 * `started` names an op whose browser call began but whose outcome was not
 * recorded (it is re-evaluated on resume, never blindly repeated).
 */
export interface BatchCursor {
  readonly batch_id: BatchId;
  readonly next_index: number;
  readonly outcomes: readonly OpOutcome[];
  readonly started?: number;
}

// --- Receipt construction ---

function appliedOf(outcomes: readonly OpOutcome[]): OpApplied[] {
  return outcomes.filter((o) => o.outcome === 'applied').map(({ index, node_id, changed }) => ({ index, node_id, changed }));
}

function skippedOf(outcomes: readonly OpOutcome[]): OpSkipped[] {
  return outcomes.filter((o) => o.outcome === 'skipped').map(({ index, reason }) => ({ index, reason }));
}

/** APPLIED: `applied` and `skipped` partition every op index, each ascending. */
export function appliedReceipt(batch_id: BatchId, outcomes: readonly OpOutcome[], snapshot: Snapshot, pre_batch: boolean): ReceiptApplied {
  const ordered = [...outcomes].sort((a, b) => a.index - b.index);
  return { state: 'APPLIED', batch_id, snapshot, pre_batch, applied: appliedOf(ordered), skipped: skippedOf(ordered) };
}
