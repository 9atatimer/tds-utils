// ops.ts -- what an operation finds already in the tree (contract v1 README,
// "Write batches", Operations): the existing child a create would duplicate,
// which is both the path-idempotence test and the post-condition of a create
// whose browser call may have happened before the worker died.

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
