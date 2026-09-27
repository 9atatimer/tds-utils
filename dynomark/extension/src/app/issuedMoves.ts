// issuedMoves.ts -- which tree moves the extension itself made (design,
// "Move": the extension adapter sets origin from the batch operations it
// itself issued). The browser reports a move some time after the call that
// made it -- possibly after the batch closed -- so each move the batch lane
// issues is remembered until the browser reports it.

import type { FolderPath, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId, Title, Url } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';

// --- Constants ---

/** Remembered moves at most; the oldest is forgotten first (its report never came). */
const MAX_REMEMBERED = 1000;

// --- The decorator ---

export class IssuedMoves implements BookmarkTreePort {
  /** Per node, the destinations issued and not yet reported, oldest first (one batch can move a node twice). */
  private readonly issued = new Map<NodeId, readonly NodeId[]>();

  constructor(private readonly inner: BookmarkTreePort) {}

  /** True, once, when the browser reports a move of `node_id` into `parent_id` that this extension issued. */
  consume(node_id: NodeId, parent_id: NodeId): boolean {
    const parents = this.issued.get(node_id) ?? [];
    const at = parents.indexOf(parent_id);
    if (at < 0) return false;
    const rest = parents.filter((_, i) => i !== at);
    if (rest.length === 0) this.issued.delete(node_id);
    else this.issued.set(node_id, rest);
    return true;
  }

  async move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    const parents = this.issued.get(nodeId) ?? [];
    this.issued.delete(nodeId);
    this.issued.set(nodeId, [...parents, parentId]);
    if (this.issued.size > MAX_REMEMBERED) this.issued.delete(this.issued.keys().next().value ?? nodeId);
    return this.inner.move(nodeId, parentId);
  }

  readTree(): Promise<TreeRead> {
    return this.inner.readTree();
  }

  resolveFolder(path: FolderPath): Promise<NodeId | undefined> {
    return this.inner.resolveFolder(path);
  }

  getNode(id: NodeId): Promise<SnapshotNode | undefined> {
    return this.inner.getNode(id);
  }

  getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]> {
    return this.inner.getChildren(folderId);
  }

  createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode> {
    return this.inner.createFolder(parentId, title);
  }

  createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode> {
    return this.inner.createBookmark(parentId, title, url);
  }
}
