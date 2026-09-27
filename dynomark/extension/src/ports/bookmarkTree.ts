// bookmarkTree.ts -- the BookmarkTreePort: the browser's native bookmark tree
// (design, seam table, "Browser tree API"; contract v1 README, "Write
// batches"). Thin over the browser API on purpose: path-idempotence, the
// boundary and preconditions are domain and use-case rules, not the port's.
// There is no delete: a removal is a move to Graveyard.

import type { FolderPath, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId, Title, Url } from '../domain/values.js';

/** The browser refused a call (missing node or parent, a protected folder, a cycle): FailReason `browser_error`. */
export class BrowserRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BrowserRefused';
  }
}

export interface BookmarkTreePort {
  /** The whole tree and the node each RootKey maps to (the syncing copy where a local-only one also exists). */
  readTree(): Promise<TreeRead>;
  /** The folder a FolderPath names, per the contract's Paths rule; undefined when a level does not resolve. */
  resolveFolder(path: FolderPath): Promise<NodeId | undefined>;
  /** One node, or undefined when no node has this id. */
  getNode(id: NodeId): Promise<SnapshotNode | undefined>;
  /** A folder's children in index order. Rejects with BrowserRefused for a missing id or a non-folder. */
  getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]>;
  /** Append a folder as the parent's last child. Rejects with BrowserRefused as the browser would. */
  createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode>;
  /** Append a bookmark with exactly this url as the parent's last child. Rejects with BrowserRefused as the browser would. */
  createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode>;
  /** Move a node, keeping its id, to the end of the parent. Rejects with BrowserRefused as the browser would. */
  move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode>;
}
