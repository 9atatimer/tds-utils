// issuedMoves.ts -- which tree moves the extension itself made (design,
// "Move": the extension adapter sets origin from the batch operations it
// itself issued). The browser reports a move some time after the call that
// made it -- possibly after the batch closed, or to the next worker when this
// one is terminated first -- so each move the batch lane issues is remembered
// in storage until the browser reports it (read once per worker, then
// written through in call order).

import { withIssued, withoutIssued, type IssuedMove } from '../domain/issuedMoves.js';
import type { FolderPath, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId, Title, Url } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { StoragePort } from '../ports/storage.js';

// --- The decorator ---

export class IssuedMoves implements BookmarkTreePort {
  /** The moves issued and not yet reported, oldest first (one batch can move a node twice); undefined until loaded. */
  private issued: readonly IssuedMove[] | undefined;
  private loading: Promise<readonly IssuedMove[]> | undefined;

  constructor(
    private readonly inner: BookmarkTreePort,
    private readonly storage: StoragePort,
  ) {}

  /** True, once, when the browser reports a move of `node_id` into `parent_id` that this extension (this worker or an earlier one) issued. */
  async consume(node_id: NodeId, parent_id: NodeId): Promise<boolean> {
    return this.forget({ node_id, parent_id });
  }

  /** Remembered before the call (the browser can report the move first); forgotten if the browser refuses it, as no report will come. */
  async move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    const issued = { node_id: nodeId, parent_id: parentId };
    await this.store(withIssued(await this.load(), issued));
    try {
      return await this.inner.move(nodeId, parentId);
    } catch (error) {
      await this.forget(issued);
      throw error;
    }
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

  /** Drop one remembered move; false when there is none. */
  private async forget(move: IssuedMove): Promise<boolean> {
    const rest = withoutIssued(await this.load(), move);
    if (rest === undefined) return false;
    await this.store(rest);
    return true;
  }

  private async load(): Promise<readonly IssuedMove[]> {
    if (this.issued !== undefined) return this.issued;
    this.loading ??= this.storage.loadIssuedMoves().then(
      (moves) => moves ?? [],
      (error: unknown) => {
        this.loading = undefined;
        throw error;
      },
    );
    const stored = await this.loading;
    this.issued ??= stored;
    return this.issued;
  }

  /** The list in memory at once (a report handled meanwhile sees it), then in storage. */
  private store(moves: readonly IssuedMove[]): Promise<void> {
    this.issued = moves;
    return this.storage.saveIssuedMoves(moves);
  }
}
