// diff.ts -- the owned outline, placements and proposed tree diffs (design,
// "TreeOutline", "pinned", "locked", "Placement", "TreeDiff / DiffItem").

import type { Operation, BatchState } from './batch.js';
import type { EntryRef } from './chat.js';
import type { FolderPath } from './tree.js';
import type { BatchId, EpochMs, Id, Identity, NodeId } from './values.js';

/** One folder of the owned subtree with its flags and item count; no URLs. */
export interface OutlineFolder {
  readonly node_id: NodeId;
  readonly path: FolderPath;
  /** Immune to rebuild and audit moves; still a placement candidate. */
  readonly pinned: boolean;
  /** Never a placement candidate; never moved, renamed or merged by any batch. */
  readonly locked: boolean;
  readonly item_count: number;
}

/** The folder skeleton of the owned subtree. */
export type TreeOutline = readonly OutlineFolder[];

/** Why an entry is where it is ("why here"). */
export interface PlacementReason {
  readonly identity: Identity;
  readonly folder: FolderPath;
  readonly neighbours: readonly EntryRef[];
  readonly rationale: string;
  readonly feedback_ids: readonly Id[];
  readonly model_id: string;
  readonly created_at: EpochMs;
}

export type DiffKind = 'audit' | 'rebuild';
export type DiffAction = 'add' | 'move' | 'merge';

/** A proposed set of adds, moves and merges (header only). */
export interface TreeDiff {
  readonly diff_id: Id;
  readonly kind: DiffKind;
  readonly proposed_at: EpochMs;
  readonly item_count: number;
  readonly unaccepted_count: number;
}

/** One line of a `TreeDiff`; accepted when `accepted_at` is recorded. */
export interface DiffItem {
  readonly item_id: Id;
  readonly diff_id: Id;
  readonly action: DiffAction;
  readonly description: string;
  readonly operations: readonly Operation[];
  readonly accepted_at: EpochMs | null;
  readonly batch_id?: BatchId;
  readonly batch_state?: BatchState;
}

/** An inverse operation the undo guard dropped, and why. */
export interface UndoDrop {
  readonly index: number;
  readonly reason: 'node_moved' | 'node_missing' | 'not_empty';
}
