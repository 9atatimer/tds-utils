/// <reference types="chrome" />
// bookmarkTree.ts -- the BookmarkTreePort on chrome.bookmarks (design, seam
// table, "Browser tree API"). Thin on purpose: path resolution is the domain
// rule over one tree read; path-idempotence and the boundary are the use
// cases'. Chrome has no separators. root_ids are read from folderType
// (Chrome 134+), preferring the syncing copy where the profile keeps an
// account and a local-only one (contract v1 README, "Write batches", Paths);
// an older Chrome falls back to its fixed ids 1, 2 and 3. Every refusal
// Chrome reports becomes BrowserRefused.

import { resolveFolderPath } from '../../domain/paths.js';
import type { FolderPath, RootIds, SnapshotNode, TreeRead } from '../../domain/tree.js';
import type { NodeId, Title, Url } from '../../domain/values.js';
import { BrowserRefused, type BookmarkTreePort } from '../../ports/bookmarkTree.js';

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
export interface BookmarksApi {
  getTree(): Promise<readonly ChromeBookmarkNode[]>;
  get(id: string): Promise<readonly ChromeBookmarkNode[]>;
  getChildren(id: string): Promise<readonly ChromeBookmarkNode[]>;
  create(details: { parentId?: string; title?: string; url?: string }): Promise<ChromeBookmarkNode>;
  move(id: string, destination: { parentId?: string }): Promise<ChromeBookmarkNode>;
}

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

function preorder(node: ChromeBookmarkNode): SnapshotNode[] {
  return [toSnapshotNode(node), ...(node.children ?? []).flatMap(preorder)];
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

// --- The adapter ---

export class ChromeBookmarkTree implements BookmarkTreePort {
  constructor(private readonly api: BookmarksApi = chrome.bookmarks) {}

  async readTree(): Promise<TreeRead> {
    const [root] = await this.api.getTree();
    if (root === undefined) throw new BrowserRefused('the bookmark tree has no root');
    return { root_ids: rootIdsOf(root), nodes: preorder(root) };
  }

  async resolveFolder(path: FolderPath): Promise<NodeId | undefined> {
    return resolveFolderPath(await this.readTree(), path);
  }

  async getNode(id: NodeId): Promise<SnapshotNode | undefined> {
    try {
      const [node] = await this.api.get(id);
      return node === undefined ? undefined : toSnapshotNode(node);
    } catch {
      return undefined;
    }
  }

  async getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]> {
    const folder = await this.getNode(folderId);
    if (folder?.kind !== 'folder') throw new BrowserRefused(`no folder ${folderId}`);
    return (await this.refusing(() => this.api.getChildren(folderId))).map(toSnapshotNode);
  }

  async createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode> {
    return toSnapshotNode(await this.refusing(() => this.api.create({ parentId, title })));
  }

  async createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode> {
    return toSnapshotNode(await this.refusing(() => this.api.create({ parentId, title, url })));
  }

  async move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    return toSnapshotNode(await this.refusing(() => this.api.move(nodeId, { parentId })));
  }

  /** Run one chrome.bookmarks call; whatever Chrome rejects with becomes BrowserRefused. */
  private async refusing<T>(call: () => Promise<T>): Promise<T> {
    try {
      return await call();
    } catch (error) {
      throw new BrowserRefused(error instanceof Error ? error.message : String(error));
    }
  }
}
