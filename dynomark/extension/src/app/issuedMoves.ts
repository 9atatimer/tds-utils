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
  private loading: Promise<void> | undefined;

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
    await this.load();
    await this.store(withIssued(this.current(), issued));
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
    await this.load();
    const rest = withoutIssued(this.current(), move);
    if (rest === undefined) return false;
    await this.store(rest);
    return true;
  }

  /**
   * The list as it is now. Callers read it synchronously after `await
   * this.load()`, never across another await: overlapping calls (a burst of
   * reports to a fresh worker, a batch move issued while a report is consumed)
   * all wait on one load, and each must change what the others left, or one
   * update is lost.
   */
  private current(): readonly IssuedMove[] {
    return this.issued ?? [];
  }

  /** Read storage once per worker; a failed read is retried by the next call. */
  private load(): Promise<void> {
    if (this.issued !== undefined) return Promise.resolve();
    this.loading ??= this.storage.loadIssuedMoves().then(
      (moves) => {
        this.issued ??= moves ?? [];
      },
      (error: unknown) => {
        this.loading = undefined;
        throw error;
      },
    );
    return this.loading;
  }

  /** The list in memory at once (a report handled meanwhile sees it), then in storage. */
  private store(moves: readonly IssuedMove[]): Promise<void> {
    this.issued = moves;
    return this.storage.saveIssuedMoves(moves);
  }
}
