// firefoxBookmarks.ts -- a tiny browser.bookmarks (Firefox) stand-in over the
// tree fake in its Firefox flavor: the BookmarkTreeNode shapes Firefox
// returns -- 12-character guids, the root and the four fixed top-level
// folders (menu, toolbar, unfiled, mobile), a `type` on every node, whole-ms
// dateAdded, and separators that carry the url `data:` -- and refusals as
// plain Errors with Firefox-like messages, never the port's BrowserRefused.
// Firefox has no onChildrenReordered event.

import type { FirefoxBookmarkNode, FirefoxBookmarksApi } from '../../src/adapters/firefox/bookmarkTree.js';
import type { SnapshotNode } from '../../src/domain/tree.js';
import type { NodeId } from '../../src/domain/values.js';
import { FakeBookmarkTree } from '../fakes/FakeBookmarkTree.js';

// --- Constants ---

/** What Firefox reports as a separator's url. */
export const SEPARATOR_URL = 'data:';

// --- The stub ---

export class FirefoxBookmarksStub implements FirefoxBookmarksApi {
  readonly fake = new FakeBookmarkTree({ flavor: 'firefox' });

  async getTree(): Promise<FirefoxBookmarkNode[]> {
    const read = await this.fake.readTree();
    const root = read.nodes.find((n) => n.parent_id === null);
    return root === undefined ? [] : [this.nest(root, read.nodes)];
  }

  async get(id: string): Promise<FirefoxBookmarkNode[]> {
    const node = await this.fake.getNode(id);
    if (node === undefined) throw new Error(`Bookmark not found: ${id}`);
    return [this.flat(node)];
  }

  async getChildren(id: string): Promise<FirefoxBookmarkNode[]> {
    return (await this.call(() => this.fake.getChildren(id))).map((n) => this.flat(n));
  }

  async create(details: { parentId?: string; title?: string; url?: string }): Promise<FirefoxBookmarkNode> {
    const parent = details.parentId ?? 'unfiled_____';
    const title = details.title ?? '';
    const made = await this.call(() =>
      details.url === undefined ? this.fake.createFolder(parent, title) : this.fake.createBookmark(parent, title, details.url),
    );
    return this.flat(made);
  }

  async move(id: string, destination: { parentId?: string }): Promise<FirefoxBookmarkNode> {
    return this.flat(await this.call(() => this.fake.move(id, destination.parentId ?? '')));
  }

  /** The user adds a separator as the folder's last child (the extension never does). */
  addSeparator(parentId: NodeId): NodeId {
    return this.fake.addSeparator(parentId);
  }

  /** The node as Firefox would report it in an event. */
  async reported(id: NodeId): Promise<FirefoxBookmarkNode> {
    const node = await this.fake.getNode(id);
    if (node === undefined) throw new Error(`FirefoxBookmarksStub: no node ${id}`);
    return this.flat(node);
  }

  private async call<T>(run: () => Promise<T>): Promise<T> {
    try {
      return await run();
    } catch (error) {
      throw new Error(error instanceof Error ? error.message : String(error));
    }
  }

  private flat(node: SnapshotNode): FirefoxBookmarkNode {
    const base = {
      id: node.id,
      title: node.title,
      index: node.index,
      dateAdded: node.date_added,
      type: node.kind,
      ...(node.parent_id === null ? {} : { parentId: node.parent_id }),
    };
    if (node.kind === 'bookmark') return { ...base, url: node.url };
    if (node.kind === 'separator') return { ...base, url: SEPARATOR_URL };
    return base;
  }

  private nest(node: SnapshotNode, all: readonly SnapshotNode[]): FirefoxBookmarkNode {
    const flat = this.flat(node);
    if (node.kind !== 'folder') return flat;
    const children = all.filter((n) => n.parent_id === node.id).sort((a, b) => a.index - b.index);
    return { ...flat, children: children.map((c) => this.nest(c, all)) };
  }
}
