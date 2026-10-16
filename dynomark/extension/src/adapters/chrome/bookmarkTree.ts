/// <reference types="chrome" />
// bookmarkTree.ts -- the BookmarkTreePort on chrome.bookmarks (design, seam
// table, "Browser tree API"): the shared WebExtensions adapter with Chrome's
// dialect. Chrome has no separators: a node with a url is a bookmark.
// root_ids are read from folderType (Chrome 134+), preferring the syncing copy
// where the profile keeps an account and a local-only one (contract v1
// README, "Write batches", Paths); an older Chrome falls back to its fixed ids
// 1, 2 and 3.

import type { RootIds, SnapshotNode } from '../../domain/tree.js';
import type { NodeId } from '../../domain/values.js';
import { BrowserRefused } from '../../ports/bookmarkTree.js';
import { WebExtBookmarkTree, type TreeDialect, type WebExtBookmarksApi } from '../webextBookmarkTree.js';

// --- Types ---

/** The fields of chrome.bookmarks.BookmarkTreeNode this adapter reads. */
export interface ChromeBookmarkNode {
  readonly id: string;
  readonly parentId?: string;
  readonly index?: number;
  readonly title: string;
  readonly url?: string;
  readonly dateAdded?: number;
  readonly folderType?: string;
  readonly syncing?: boolean;
  readonly children?: readonly ChromeBookmarkNode[];
}

/** The part of chrome.bookmarks this adapter uses. */
export type BookmarksApi = WebExtBookmarksApi<ChromeBookmarkNode>;

// --- Constants ---

const FOLDER_TYPE_KEYS = { 'bookmarks-bar': 'bar', other: 'other', mobile: 'mobile' } as const;
/** Chrome's fixed top-level ids before folderType existed. */
const LEGACY_ROOT_IDS: RootIds = { bar: '1', other: '2', mobile: '3' };

// --- Pure helpers ---

/** One chrome.bookmarks node as the domain's SnapshotNode (whole-ms date_added; a url makes it a bookmark). */
export function toSnapshotNode(node: ChromeBookmarkNode): SnapshotNode {
  const base = {
    id: node.id,
    parent_id: node.parentId ?? null,
    index: node.index ?? 0,
    title: node.title,
    date_added: Math.max(0, Math.floor(node.dateAdded ?? 0)),
  };
  return node.url === undefined ? { ...base, kind: 'folder' } : { ...base, kind: 'bookmark', url: node.url };
}

/** The top-level folder of one folder type: the syncing copy when there are several. */
function topLevelOf(top: readonly ChromeBookmarkNode[], folderType: string): NodeId | undefined {
  const typed = top.filter((n) => n.folderType === folderType);
  return (typed.find((n) => n.syncing === true) ?? typed[0])?.id;
}

function rootIdsOf(root: ChromeBookmarkNode): RootIds {
  const top = root.children ?? [];
  if (!top.some((n) => n.folderType !== undefined)) return LEGACY_ROOT_IDS;
  const ids: Partial<Record<'bar' | 'other' | 'mobile', NodeId>> = {};
  for (const [type, key] of Object.entries(FOLDER_TYPE_KEYS)) {
    const id = topLevelOf(top, type);
    if (id !== undefined) ids[key] = id;
  }
  if (ids.bar === undefined || ids.other === undefined) throw new BrowserRefused('the bookmarks bar or Other bookmarks is missing');
  return { bar: ids.bar, other: ids.other, ...(ids.mobile === undefined ? {} : { mobile: ids.mobile }) };
}

const CHROME_DIALECT: TreeDialect<ChromeBookmarkNode> = { toSnapshotNode, rootIdsOf };

// --- The adapter ---

export class ChromeBookmarkTree extends WebExtBookmarkTree<ChromeBookmarkNode> {
  constructor(api: BookmarksApi = chrome.bookmarks) {
    super(api, CHROME_DIALECT);
  }
}
