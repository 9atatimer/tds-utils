// webextBookmarkTree.ts -- the BookmarkTreePort over a WebExtensions
// bookmarks API, shared by the Chrome and Firefox adapters (design, seam
// table, "Browser tree API"): both browsers expose the same calls and differ
// only in their node shape (Firefox types every node and has separators) and
// in which top-level folders the root keys name. A browser supplies those two
// as its TreeDialect. Thin on purpose: path resolution is the domain rule over
// one tree read; path-idempotence and the boundary are the use cases'. Every
// refusal the browser reports becomes BrowserRefused.

import { resolveFolderPath } from '../domain/paths.js';
import type { FolderPath, RootIds, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId, Title, Url } from '../domain/values.js';
import { BrowserRefused, type BookmarkTreePort } from '../ports/bookmarkTree.js';

// --- Types ---

/** The fields of a WebExtensions BookmarkTreeNode every browser reports. */
export interface WebExtBookmarkNode {
  readonly id: string;
  readonly parentId?: string;
  readonly children?: readonly WebExtBookmarkNode[];
}

/** The part of a WebExtensions bookmarks API this adapter uses, over the browser's node shape N. */
export interface WebExtBookmarksApi<N> {
  getTree(): Promise<readonly N[]>;
  get(id: string): Promise<readonly N[]>;
  getChildren(id: string): Promise<readonly N[]>;
  create(details: { parentId?: string; title?: string; url?: string }): Promise<N>;
  move(id: string, destination: { parentId?: string }): Promise<N>;
}

/** What one browser's tree means: a node as the domain's SnapshotNode, and the node each RootKey maps to. */
export interface TreeDialect<N> {
  toSnapshotNode(node: N): SnapshotNode;
  /** Throws BrowserRefused when the bar or other folder is missing. */
  rootIdsOf(root: N): RootIds;
}

// --- The adapter ---

export class WebExtBookmarkTree<N extends WebExtBookmarkNode> implements BookmarkTreePort {
  constructor(
    private readonly api: WebExtBookmarksApi<N>,
    private readonly dialect: TreeDialect<N>,
  ) {}

  async readTree(): Promise<TreeRead> {
    const [root] = await this.api.getTree();
    if (root === undefined) throw new BrowserRefused('the bookmark tree has no root');
    return { root_ids: this.dialect.rootIdsOf(root), nodes: this.preorder(root) };
  }

  async resolveFolder(path: FolderPath): Promise<NodeId | undefined> {
    return resolveFolderPath(await this.readTree(), path);
  }

  async getNode(id: NodeId): Promise<SnapshotNode | undefined> {
    try {
      const [node] = await this.api.get(id);
      return node === undefined ? undefined : this.dialect.toSnapshotNode(node);
    } catch {
      return undefined;
    }
  }

  async getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]> {
    const folder = await this.getNode(folderId);
    if (folder?.kind !== 'folder') throw new BrowserRefused(`no folder ${folderId}`);
    return (await this.refusing(() => this.api.getChildren(folderId))).map((n) => this.dialect.toSnapshotNode(n));
  }

  async createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode> {
    return this.dialect.toSnapshotNode(await this.refusing(() => this.api.create({ parentId, title })));
  }

  async createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode> {
    return this.dialect.toSnapshotNode(await this.refusing(() => this.api.create({ parentId, title, url })));
  }

  async move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    return this.dialect.toSnapshotNode(await this.refusing(() => this.api.move(nodeId, { parentId })));
  }

  private preorder(node: N): SnapshotNode[] {
    return [this.dialect.toSnapshotNode(node), ...((node.children ?? []) as readonly N[]).flatMap((c) => this.preorder(c))];
  }

  /** Run one bookmarks call; whatever the browser rejects with becomes BrowserRefused. */
  private async refusing<T>(call: () => Promise<T>): Promise<T> {
    try {
      return await call();
    } catch (error) {
      throw new BrowserRefused(error instanceof Error ? error.message : String(error));
    }
  }
}
