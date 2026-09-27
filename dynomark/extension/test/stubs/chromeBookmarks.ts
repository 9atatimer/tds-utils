// chromeBookmarks.ts -- a tiny chrome.bookmarks stand-in over the tree fake:
// the nested BookmarkTreeNode shapes Chrome returns (folderType and syncing
// on the top-level folders, Chrome 134+), and refusals as plain Errors with
// Chrome-like messages, never the port's BrowserRefused.

import type { BookmarksApi, ChromeBookmarkNode } from '../../src/adapters/chrome/bookmarkTree.js';
import type { SnapshotNode } from '../../src/domain/tree.js';
import { FakeBookmarkTree } from '../fakes/FakeBookmarkTree.js';

// --- Constants ---

const FOLDER_TYPES: Readonly<Record<string, 'bookmarks-bar' | 'other' | 'mobile'>> = {
  'Bookmarks bar': 'bookmarks-bar',
  'Other bookmarks': 'other',
  'Mobile bookmarks': 'mobile',
};

// --- The stub ---

export class BookmarksApiStub implements BookmarksApi {
  readonly fake: FakeBookmarkTree;
  /** Set false to model a Chrome before 134: no folderType on the top-level folders. */
  folderTypes = true;

  constructor(options: { readonly accountStorage?: boolean } = {}) {
    this.fake = new FakeBookmarkTree({ flavor: 'chrome', ...(options.accountStorage === undefined ? {} : options) });
  }

  async getTree(): Promise<ChromeBookmarkNode[]> {
    const read = await this.fake.readTree();
    const root = read.nodes.find((n) => n.parent_id === null);
    return root === undefined ? [] : [this.nest(root, read.nodes)];
  }

  async get(id: string): Promise<ChromeBookmarkNode[]> {
    const node = await this.fake.getNode(id);
    if (node === undefined) throw new Error("Can't find bookmark for id.");
    return [this.flat(node)];
  }

  async getChildren(id: string): Promise<ChromeBookmarkNode[]> {
    return (await this.call(() => this.fake.getChildren(id))).map((n) => this.flat(n));
  }

  async create(details: { parentId?: string; title?: string; url?: string }): Promise<ChromeBookmarkNode> {
    const parent = details.parentId ?? '2';
    const title = details.title ?? '';
    const made = await this.call(() =>
      details.url === undefined ? this.fake.createFolder(parent, title) : this.fake.createBookmark(parent, title, details.url),
    );
    return this.flat(made);
  }

  async move(id: string, destination: { parentId?: string }): Promise<ChromeBookmarkNode> {
    return this.flat(await this.call(() => this.fake.move(id, destination.parentId ?? '')));
  }

  private async call<T>(run: () => Promise<T>): Promise<T> {
    try {
      return await run();
    } catch (error) {
      throw new Error(error instanceof Error ? error.message : String(error));
    }
  }

  private flat(node: SnapshotNode): ChromeBookmarkNode {
    const base: ChromeBookmarkNode = {
      id: node.id,
      title: node.title,
      index: node.index,
      dateAdded: node.date_added + 0.5,
      syncing: this.fake.isSyncing(node.id),
      ...(node.parent_id === null ? {} : { parentId: node.parent_id }),
      ...(node.kind === 'bookmark' ? { url: node.url } : {}),
    };
    const folderType = node.parent_id === '0' && this.folderTypes ? FOLDER_TYPES[node.title] : undefined;
    return folderType === undefined ? base : { ...base, folderType };
  }

  private nest(node: SnapshotNode, all: readonly SnapshotNode[]): ChromeBookmarkNode {
    const flat = this.flat(node);
    if (node.kind !== 'folder') return flat;
    const children = all.filter((n) => n.parent_id === node.id).sort((a, b) => a.index - b.index);
    return { ...flat, children: children.map((c) => this.nest(c, all)) };
  }
}
