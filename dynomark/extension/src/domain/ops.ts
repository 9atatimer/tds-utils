// ops.ts -- what an operation finds already in the tree (contract v1 README,
// "Write batches", Operations): the existing child a create would duplicate,
// which is both the path-idempotence test and the post-condition of a create
// whose browser call may have happened before the worker died.

import type { Expect, SkipReason } from './batch.js';
import { pickChildFolder } from './paths.js';
import type { SnapshotNode } from './tree.js';
import type { NodeId, Title, Url } from './values.js';

// --- Pure helpers ---

/** The child folder of `parentId` titled exactly `title` (well-formed compare), lowest index first. */
export function existingFolder(children: readonly SnapshotNode[], parentId: NodeId, title: Title): SnapshotNode | undefined {
  return pickChildFolder(children, parentId, title);
}

/** The child bookmark of `parentId` whose url is exactly `url`, lowest index first. */
export function existingBookmark(children: readonly SnapshotNode[], parentId: NodeId, url: Url): SnapshotNode | undefined {
  return children
    .filter((n) => n.parent_id === parentId && n.kind === 'bookmark' && n.url === url)
    .reduce<SnapshotNode | undefined>((best, n) => (best === undefined || n.index < best.index ? n : best), undefined);
}

// --- Preconditions ---

/** The facts a move or remove's `expect` is checked against, read from the tree before the op. */
export interface ExpectFacts {
  /** The node's parent now. */
  readonly parent_id: NodeId | null;
  /** The folder `expect.parent_path` resolves to, when the clause is present. */
  readonly parent_path_id?: NodeId | undefined;
  /** The node's kind and child count, for `expect.empty`. */
  readonly is_folder: boolean;
  readonly child_count: number;
}

/** The first `expect` clause that fails, as a SkipReason; undefined when every clause holds. */
export function expectFailure(expect: Expect, facts: ExpectFacts): SkipReason | undefined {
  if (facts.parent_id !== expect.parent_id) return 'parent_mismatch';
  if (expect.parent_path !== undefined && facts.parent_path_id !== facts.parent_id) return 'parent_mismatch';
  if (expect.empty === true && (!facts.is_folder || facts.child_count > 0)) return 'not_empty';
  return undefined;
}
