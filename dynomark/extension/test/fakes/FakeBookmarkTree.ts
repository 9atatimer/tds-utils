// FakeBookmarkTree.ts -- an in-memory BookmarkTreePort for one browser profile.
//
// Models what the real trees do that the use cases depend on: per-profile node
// ids (Chrome decimal strings, Firefox 12-character guids), the four root keys
// (menu on Firefox only), folders, bookmarks and Firefox separators, Chrome's
// account-storage copies of the top-level folders (root_ids name the syncing
// copy), the browser's refusals, and user edits made behind the extension's
// back. Path resolution goes through the domain rule, as the adapters will.

import { resolveFolderPath } from '../../src/domain/paths.js';
import type { FolderPath, NodeKind, RootIds, SnapshotNode, TreeRead } from '../../src/domain/tree.js';
import type { EpochMs, NodeId, Title, Url } from '../../src/domain/values.js';
import { BrowserRefused, type BookmarkTreePort } from '../../src/ports/bookmarkTree.js';
import type { Clock } from '../../src/ports/clock.js';
import { WorkerTerminated } from './WorkerTerminated.js';

// --- Constants ---

const FIRST_DATE_ADDED: EpochMs = 1_789_990_000_000;

type Flavor = 'chrome' | 'firefox';

/**
 * How an armed mutating call fails: `refuse` (the browser refuses; tree
 * unchanged), `terminate-before` (the worker dies before the browser acts) or
 * `terminate-after` (the browser acts, then the worker dies before hearing).
 */
export type MutationFault = 'refuse' | 'terminate-before' | 'terminate-after';

export interface FakeBookmarkTreeOptions {
  readonly flavor: Flavor;
  /** Chrome only: the profile also keeps local-only copies of the top-level folders. */
  readonly accountStorage?: boolean;
  /** Source of date_added for new nodes; a fixed sequence when absent. */
  readonly clock?: Clock;
}

interface StoredNode {
  readonly id: NodeId;
  parent_id: NodeId | null;
  readonly kind: NodeKind;
  readonly title: Title;
  readonly url?: Url;
  readonly date_added: EpochMs;
  readonly syncing: boolean;
}

interface TopLevel {
  readonly id: NodeId;
  readonly title: Title;
  readonly syncing: boolean;
}

// --- Browser shapes ---

function chromeTopLevel(accountStorage: boolean): { readonly folders: TopLevel[]; readonly rootIds: RootIds } {
  const local = [
    { id: '1', title: 'Bookmarks bar', syncing: !accountStorage },
    { id: '2', title: 'Other bookmarks', syncing: !accountStorage },
    { id: '3', title: 'Mobile bookmarks', syncing: !accountStorage },
  ];
  if (!accountStorage) return { folders: local, rootIds: { bar: '1', other: '2', mobile: '3' } };
  const account = [
    { id: '4', title: 'Bookmarks bar', syncing: true },
    { id: '5', title: 'Other bookmarks', syncing: true },
    { id: '6', title: 'Mobile bookmarks', syncing: true },
  ];
  return { folders: [...local, ...account], rootIds: { bar: '4', other: '5', mobile: '6' } };
}

function firefoxTopLevel(): { readonly folders: TopLevel[]; readonly rootIds: RootIds } {
  return {
    folders: [
      { id: 'menu________', title: 'Bookmarks Menu', syncing: true },
      { id: 'toolbar_____', title: 'Bookmarks Toolbar', syncing: true },
      { id: 'unfiled_____', title: 'Other Bookmarks', syncing: true },
      { id: 'mobile______', title: 'Mobile Bookmarks', syncing: true },
    ],
    rootIds: { bar: 'toolbar_____', other: 'unfiled_____', mobile: 'mobile______', menu: 'menu________' },
  };
}

// --- The fake ---

export class FakeBookmarkTree implements BookmarkTreePort {
  private readonly flavor: Flavor;
  private readonly clock: Clock | undefined;
  private readonly rootId: NodeId;
  private readonly rootIds: RootIds;
  private readonly nodes = new Map<NodeId, StoredNode>();
  private readonly children = new Map<NodeId, NodeId[]>();
  private created = 0;
  private mutations = 0;
  private fault: { readonly at: number; readonly mode: MutationFault } | undefined;

  constructor(options: FakeBookmarkTreeOptions) {
    this.flavor = options.flavor;
    this.clock = options.clock;
    this.rootId = this.flavor === 'chrome' ? '0' : 'root________';
    const top = this.flavor === 'chrome' ? chromeTopLevel(options.accountStorage ?? false) : firefoxTopLevel();
    this.rootIds = top.rootIds;
    this.store({ id: this.rootId, parent_id: null, kind: 'folder', title: '', date_added: FIRST_DATE_ADDED, syncing: true });
    for (const t of top.folders) {
      this.store({ id: t.id, parent_id: this.rootId, kind: 'folder', title: t.title, date_added: FIRST_DATE_ADDED, syncing: t.syncing });
    }
    this.created = top.folders.length;
  }

  // --- BookmarkTreePort ---

  readTree(): Promise<TreeRead> {
    return Promise.resolve({ root_ids: { ...this.rootIds }, nodes: this.preorder(this.rootId) });
  }

  async resolveFolder(path: FolderPath): Promise<NodeId | undefined> {
    return resolveFolderPath(await this.readTree(), path);
  }

  getNode(id: NodeId): Promise<SnapshotNode | undefined> {
    return Promise.resolve(this.nodes.has(id) ? this.view(id) : undefined);
  }

  getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]> {
    return this.attempt(() => {
      this.requireFolder(folderId);
      return (this.children.get(folderId) ?? []).map((id) => this.view(id));
    });
  }

  createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode> {
    return this.attempt(() => this.mutate(() => this.view(this.append(parentId, 'folder', title))));
  }

  createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode> {
    return this.attempt(() => this.mutate(() => this.view(this.append(parentId, 'bookmark', title, url))));
  }

  move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    return this.attempt(() => this.mutate(() => this.moveNow(nodeId, parentId)));
  }

  // --- Fake-only arrangement ---

  /** Make the `at`-th mutating port call from now (1-based: createFolder, createBookmark, move) fail as `mode` says, once. */
  failOnMutation(at: number, mode: MutationFault): void {
    this.mutations = 0;
    this.fault = { at, mode };
  }

  /** Firefox only: seed a separator as the folder's last child. */
  addSeparator(parentId: NodeId): NodeId {
    if (this.flavor !== 'firefox') throw new Error('FakeBookmarkTree: Chrome has no separator nodes');
    return this.append(parentId, 'separator', '');
  }

  /** The user deletes a node and everything under it (the extension never can). */
  deleteByUser(id: NodeId): void {
    for (const child of [...(this.children.get(id) ?? [])]) this.deleteByUser(child);
    this.detach(id);
    this.children.delete(id);
    this.nodes.delete(id);
  }

  /** True when the node is the syncing copy (false for Chrome's local-only top-level copies). */
  isSyncing(id: NodeId): boolean {
    return this.nodes.get(id)?.syncing ?? false;
  }

  // --- Internals ---

  /** Count one mutating call and apply the armed fault, if this is its call. */
  private mutate<T>(call: () => T): T {
    this.mutations += 1;
    const fault = this.fault?.at === this.mutations ? this.fault : undefined;
    if (fault !== undefined) this.fault = undefined;
    if (fault?.mode === 'refuse') throw new BrowserRefused(`refused at mutation ${this.mutations} (injected)`);
    if (fault?.mode === 'terminate-before') throw new WorkerTerminated();
    const result = call();
    if (fault?.mode === 'terminate-after') throw new WorkerTerminated();
    return result;
  }

  private moveNow(nodeId: NodeId, parentId: NodeId): SnapshotNode {
    const node = this.nodes.get(nodeId);
    if (node === undefined) throw new BrowserRefused(`no node ${nodeId}`);
    if (this.isProtected(nodeId)) throw new BrowserRefused(`cannot move the root or a top-level folder (${nodeId})`);
    this.requireWritableFolder(parentId);
    if (this.isSelfOrAncestor(nodeId, parentId)) throw new BrowserRefused(`cannot move ${nodeId} into itself or a descendant`);
    this.detach(nodeId);
    node.parent_id = parentId;
    this.children.get(parentId)?.push(nodeId);
    return this.view(nodeId);
  }

  /** Run one browser call: a thrown refusal becomes a rejected promise, as the real API reports it. */
  private attempt<T>(call: () => T): Promise<T> {
    try {
      return Promise.resolve(call());
    } catch (error) {
      return Promise.reject(error instanceof Error ? error : new Error(String(error)));
    }
  }

  private append(parentId: NodeId, kind: NodeKind, title: Title, url?: Url): NodeId {
    this.requireWritableFolder(parentId);
    const id = this.nextId();
    const date_added = this.clock?.now() ?? FIRST_DATE_ADDED + this.created * 1000;
    this.store({ id, parent_id: parentId, kind, title, ...(url === undefined ? {} : { url }), date_added, syncing: true });
    return id;
  }

  private store(node: StoredNode): void {
    this.nodes.set(node.id, node);
    if (node.kind === 'folder') this.children.set(node.id, []);
    if (node.parent_id !== null) this.children.get(node.parent_id)?.push(node.id);
  }

  private nextId(): NodeId {
    this.created += 1;
    return this.flavor === 'chrome' ? String(this.created) : `g${String(this.created).padStart(11, '0')}`;
  }

  private requireFolder(id: NodeId): void {
    if (this.nodes.get(id)?.kind !== 'folder') throw new BrowserRefused(`no folder ${id}`);
  }

  private requireWritableFolder(id: NodeId): void {
    this.requireFolder(id);
    if (id === this.rootId) throw new BrowserRefused('cannot modify the browser root folder');
  }

  private isProtected(id: NodeId): boolean {
    return id === this.rootId || this.nodes.get(id)?.parent_id === this.rootId;
  }

  private isSelfOrAncestor(candidate: NodeId, of: NodeId): boolean {
    for (let at: NodeId | null | undefined = of; at != null; at = this.nodes.get(at)?.parent_id) {
      if (at === candidate) return true;
    }
    return false;
  }

  private detach(id: NodeId): void {
    const parent = this.nodes.get(id)?.parent_id;
    const siblings = parent == null ? undefined : this.children.get(parent);
    if (siblings !== undefined) siblings.splice(siblings.indexOf(id), 1);
  }

  private view(id: NodeId): SnapshotNode {
    const n = this.nodes.get(id);
    if (n === undefined) throw new Error(`FakeBookmarkTree: no node ${id}`);
    const index = n.parent_id === null ? 0 : (this.children.get(n.parent_id)?.indexOf(id) ?? 0);
    const base = { id: n.id, parent_id: n.parent_id, index, title: n.title, date_added: n.date_added };
    if (n.kind === 'bookmark') return { ...base, kind: 'bookmark', url: n.url ?? '' };
    return { ...base, kind: n.kind };
  }

  private preorder(id: NodeId): SnapshotNode[] {
    return [this.view(id), ...(this.children.get(id) ?? []).flatMap((child) => this.preorder(child))];
  }
}
