// paths.ts -- FolderPath resolution, the one owner of the rule (contract v1
// README, "Write batches", Paths). Pure over a tree read; the tree port and
// its fake resolve through it, and so will the boundary check.

import { toWellFormed } from './text.js';
import type { FolderPath, SnapshotNode, TreeRead } from './tree.js';
import type { NodeId, Title } from './values.js';

// --- Predicates ---

/** True when the node is a folder directly in `parentId` whose well-formed title equals the well-formed `name`. */
function isFolderNamed(node: SnapshotNode, parentId: NodeId, name: Title): boolean {
  return node.kind === 'folder' && node.parent_id === parentId && toWellFormed(node.title) === toWellFormed(name);
}

// --- Pure helpers ---

/** The child folder of `parentId` titled `name` with the lowest index, if any. */
export function pickChildFolder(nodes: readonly SnapshotNode[], parentId: NodeId, name: Title): SnapshotNode | undefined {
  return nodes
    .filter((n) => isFolderNamed(n, parentId, name))
    .reduce<SnapshotNode | undefined>((best, n) => (best === undefined || n.index < best.index ? n : best), undefined);
}

/** The node id a `FolderPath` names in this tree, or undefined when any level does not resolve. */
export function resolveFolderPath(tree: TreeRead, path: FolderPath): NodeId | undefined {
  let current: NodeId | undefined = tree.root_ids[path.root];
  for (const name of path.names) {
    if (current === undefined) return undefined;
    current = pickChildFolder(tree.nodes, current, name)?.id;
  }
  return current;
}
