// followUp.ts -- which folder is Follow Up (design, "The extension", Watch
// Follow Up; contract v1 README, "Connection lifecycle", step 1). Zero
// folders named Follow Up: create one directly under the bookmarks bar. More
// than one: use the one directly under the bar (the lowest index, as the
// Paths rule picks) and report the others. Only a folder its own FolderPath
// resolves back to can be named on the wire, so only such a folder is used.

import { folderPathOf, resolveFolderPath } from './paths.js';
import { toWellFormed } from './text.js';
import { ROOT_KEYS, type FolderPath, type SnapshotNode, type TreeRead } from './tree.js';
import type { NodeId, Title } from './values.js';

// --- Constants ---

/** The folder a save goes into to be filed. */
export const FOLLOW_UP_TITLE: Title = 'Follow Up';

// --- Types ---

/** Create Follow Up in `parent`, or use the folder `node_id` at `path` and report `others`. */
export type FollowUpResolution =
  | { readonly kind: 'create'; readonly parent: FolderPath; readonly title: Title }
  | { readonly kind: 'use'; readonly node_id: NodeId; readonly path: FolderPath; readonly others: readonly NodeId[] };

interface Candidate {
  readonly id: NodeId;
  readonly path: FolderPath;
  /** Root key rank, then the index of each ancestor downward: sorts in tree (preorder) order. */
  readonly order: readonly number[];
}

// --- Pure helpers ---

function orderOf(node: SnapshotNode, byId: ReadonlyMap<NodeId, SnapshotNode>, path: FolderPath): number[] {
  const chain: number[] = [];
  for (let at: SnapshotNode | undefined = node; at !== undefined && chain.length <= path.names.length - 1;) {
    chain.unshift(at.index);
    at = at.parent_id === null ? undefined : byId.get(at.parent_id);
  }
  return [ROOT_KEYS.indexOf(path.root), ...chain];
}

function compareOrder(a: Candidate, b: Candidate): number {
  for (let i = 0; i < Math.max(a.order.length, b.order.length); i += 1) {
    const d = (a.order[i] ?? -1) - (b.order[i] ?? -1);
    if (d !== 0) return d;
  }
  return 0;
}

/** Every folder titled `title` (well-formed compare), in the order the tree read lists them. */
function namedFolders(tree: TreeRead, title: Title): SnapshotNode[] {
  const wanted = toWellFormed(title);
  return tree.nodes.filter((node) => node.kind === 'folder' && toWellFormed(node.title) === wanted);
}

/** The named folders a FolderPath resolves back to: the only ones that can be named on the wire. */
function candidatesOf(tree: TreeRead, named: readonly SnapshotNode[]): Candidate[] {
  const byId = new Map(tree.nodes.map((n) => [n.id, n] as const));
  return named.flatMap((node) => {
    const path = folderPathOf(tree, node.id);
    if (path === undefined || resolveFolderPath(tree, path) !== node.id) return [];
    return [{ id: node.id, path, order: orderOf(node, byId, path) }];
  });
}

/** The Follow Up folder the extension watches, or where to create it. */
export function resolveFollowUp(tree: TreeRead, title: Title = FOLLOW_UP_TITLE): FollowUpResolution {
  const named = namedFolders(tree, title);
  const found = candidatesOf(tree, named).sort(compareOrder);
  if (found.length === 0) return { kind: 'create', parent: { root: 'bar', names: [] }, title };
  const onBar = found.find((c) => c.path.root === 'bar' && c.path.names.length === 1);
  const chosen = onBar ?? found[0];
  if (chosen === undefined) return { kind: 'create', parent: { root: 'bar', names: [] }, title };
  return { kind: 'use', node_id: chosen.id, path: chosen.path, others: named.filter((n) => n.id !== chosen.id).map((n) => n.id) };
}
