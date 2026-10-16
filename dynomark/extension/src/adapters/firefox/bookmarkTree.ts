// bookmarkTree.ts -- the BookmarkTreePort on Firefox's browser.bookmarks
// (design, seam table: the second "Browser tree API" adapter; task-032): the
// shared WebExtensions adapter with Firefox's dialect. Firefox types every
// node (`bookmark`, `folder`, `separator`) and reports a url (`data:`) on a
// separator, so the kind is read from the type, never from whether a url is
// present. Its top-level folders have fixed guids: the root keys map to the
// toolbar, unfiled, mobile and menu folders (contract v1 README, "Write
// batches", Paths). Firefox keeps no local-only copies of them.

import type { RootIds, SnapshotNode } from '../../domain/tree.js';
import type { NodeId } from '../../domain/values.js';
import { BrowserRefused } from '../../ports/bookmarkTree.js';
import { WebExtBookmarkTree, type TreeDialect, type WebExtBookmarksApi } from '../webextBookmarkTree.js';

// --- Types ---

/** The fields of Firefox's bookmarks.BookmarkTreeNode this adapter reads. */
export interface FirefoxBookmarkNode {
  readonly id: string;
  readonly parentId?: string;
  readonly index?: number;
  readonly title: string;
  readonly url?: string;
  readonly dateAdded?: number;
  readonly type?: 'bookmark' | 'folder' | 'separator';
  readonly children?: readonly FirefoxBookmarkNode[];
}

/** The part of browser.bookmarks this adapter uses. */
export type FirefoxBookmarksApi = WebExtBookmarksApi<FirefoxBookmarkNode>;

// --- Constants ---

/** Firefox's fixed guids of the top-level folders, by the RootKey each is. */
const ROOT_GUIDS = { bar: 'toolbar_____', other: 'unfiled_____', mobile: 'mobile______', menu: 'menu________' } as const;

// --- Pure helpers ---

/** One browser.bookmarks node as the domain's SnapshotNode (whole-ms date_added; the type decides the kind). */
export function toFirefoxSnapshotNode(node: FirefoxBookmarkNode): SnapshotNode {
  const base = {
    id: node.id,
    parent_id: node.parentId ?? null,
    index: node.index ?? 0,
    title: node.title,
    date_added: Math.max(0, Math.floor(node.dateAdded ?? 0)),
  };
  if (node.type === 'separator') return { ...base, kind: 'separator' };
  if (node.type === 'folder' || node.url === undefined) return { ...base, kind: 'folder' };
  return { ...base, kind: 'bookmark', url: node.url };
}

function rootIdsOf(root: FirefoxBookmarkNode): RootIds {
  const present = new Set((root.children ?? []).map((n) => n.id));
  const has = (guid: NodeId): boolean => present.has(guid);
  if (!has(ROOT_GUIDS.bar) || !has(ROOT_GUIDS.other)) throw new BrowserRefused('the Bookmarks Toolbar or Other Bookmarks is missing');
  return {
    bar: ROOT_GUIDS.bar,
    other: ROOT_GUIDS.other,
    ...(has(ROOT_GUIDS.mobile) ? { mobile: ROOT_GUIDS.mobile } : {}),
    ...(has(ROOT_GUIDS.menu) ? { menu: ROOT_GUIDS.menu } : {}),
  };
}

const FIREFOX_DIALECT: TreeDialect<FirefoxBookmarkNode> = { toSnapshotNode: toFirefoxSnapshotNode, rootIdsOf };

// --- The adapter ---

export class FirefoxBookmarkTree extends WebExtBookmarkTree<FirefoxBookmarkNode> {
  constructor(api: FirefoxBookmarksApi) {
    super(api, FIREFOX_DIALECT);
  }
}
