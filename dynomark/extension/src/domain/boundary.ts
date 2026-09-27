// boundary.ts -- which batches the extension admits (design Goal 8, "Ownership
// boundary"; contract v1 README, "Write batches", Boundary). Checked once,
// before the first op, against the snapshot read at the start of the attempt.
// OwnedRoots is a value passed in, never a literal here.

import type { Operation, RejectReason, WriteBatch } from './batch.js';
import { isPathInside, resolveFolderPath } from './paths.js';
import type { FolderPath, OwnedRoots, SnapshotNode, TreeRead } from './tree.js';
import type { HostId, NodeId } from './values.js';

// --- Constants ---

/** A writer marker is an empty folder titled exactly this plus the writer's host id, directly in owned_roots.dynomark. */
export const WRITER_MARKER_PREFIX = 'dynomark-writer:';

// --- Predicates ---

function ownedRootList(roots: OwnedRoots): FolderPath[] {
  return [roots.follow_up, roots.dynomark, roots.graveyard];
}

function isOwnedTarget(path: FolderPath, roots: OwnedRoots): boolean {
  return ownedRootList(roots).some((root) => isPathInside(path, root));
}

/** True when (`parent`, `title`) is exactly an owned root: how the daemon creates Dynomark and Graveyard on a fresh tree. */
function isOwnedRootCreation(parent: FolderPath, title: string, roots: OwnedRoots): boolean {
  return ownedRootList(roots).some(
    (root) =>
      root.names.length > 0 &&
      root.root === parent.root &&
      root.names.at(-1) === title &&
      root.names.length === parent.names.length + 1 &&
      parent.names.every((name, i) => root.names[i] === name),
  );
}

/** True when one of the node's ancestors, starting at its parent, is a node an owned root resolves to. */
function hasOwnedAncestor(node: SnapshotNode, byId: ReadonlyMap<NodeId, SnapshotNode>, ownedIds: ReadonlySet<NodeId>): boolean {
  const seen = new Set<NodeId>();
  for (let at = node.parent_id; at !== null && !seen.has(at); at = byId.get(at)?.parent_id ?? null) {
    if (ownedIds.has(at)) return true;
    seen.add(at);
  }
  return false;
}

/** True when op indices are exactly 0..n-1 in order. */
export function hasValidIndices(batch: WriteBatch): boolean {
  return batch.operations.every((op, i) => op.index === i);
}

/** True when owned_roots.dynomark holds a writer marker of a host other than `host_id`. */
export function hasForeignWriterMarker(tree: TreeRead, roots: OwnedRoots, host_id: HostId): boolean {
  const dynomark = resolveFolderPath(tree, roots.dynomark);
  if (dynomark === undefined) return false;
  return tree.nodes.some(
    (n) =>
      n.kind === 'folder' &&
      n.parent_id === dynomark &&
      n.title.startsWith(WRITER_MARKER_PREFIX) &&
      n.title.slice(WRITER_MARKER_PREFIX.length) !== host_id,
  );
}

// --- Pure helpers ---

function admitsOp(op: Operation, roots: OwnedRoots, byId: ReadonlyMap<NodeId, SnapshotNode>, ownedIds: ReadonlySet<NodeId>): boolean {
  switch (op.op) {
    case 'create_folder':
      return isOwnedTarget(op.parent, roots) || isOwnedRootCreation(op.parent, op.title, roots);
    case 'create':
      return isOwnedTarget(op.parent, roots);
    case 'move':
    case 'remove': {
      if (op.op === 'move' && !isOwnedTarget(op.to, roots)) return false;
      const node = byId.get(op.node_id);
      return node === undefined || hasOwnedAncestor(node, byId, ownedIds);
    }
  }
}

/** True when some op of a batch without a DiffItem reference lies outside the owned roots. */
export function crossesBoundary(batch: WriteBatch, roots: OwnedRoots, tree: TreeRead): boolean {
  if (batch.diff_item_id !== undefined) return false;
  const byId = new Map(tree.nodes.map((n) => [n.id, n] as const));
  const ownedIds = new Set(ownedRootList(roots).flatMap((root) => resolveFolderPath(tree, root) ?? []));
  return batch.operations.some((op) => !admitsOp(op, roots, byId, ownedIds));
}

/**
 * Why the batch must be REJECTED before its first op, or undefined when it is
 * admitted. `conflict_reported`: the daemon's writer.status (or a
 * writer_conflict refusal) says this writer is in conflict -- no batch is
 * applied then, marker in this tree or not (task-030).
 */
export function rejectionOf(
  batch: WriteBatch,
  roots: OwnedRoots,
  host_id: HostId,
  tree: TreeRead,
  conflict_reported = false,
): RejectReason | undefined {
  if (!hasValidIndices(batch)) return 'invalid';
  if (conflict_reported || hasForeignWriterMarker(tree, roots, host_id)) return 'writer_conflict';
  if (crossesBoundary(batch, roots, tree)) return 'boundary';
  return undefined;
}
