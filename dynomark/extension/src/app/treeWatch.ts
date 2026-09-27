// treeWatch.ts -- what each bookmark event means (design, "The extension":
// Watch Follow Up, Capture from the open tab, Record feedback; contract v1
// README, "Connection lifecycle", steps 5 and 6). A bookmark created in, or
// moved into, Follow Up is captured and ingested; a move is reported as
// move.observed when both ends are owned; a change under the owned roots
// schedules one debounced tree.snapshot. Every step is short and repeatable:
// the worker can die between any two events, and ingest is idempotent. The
// saves owed a background capture are stored, so a worker that dies before
// the hello that pays them does not lose the debt; a save is owed one from
// before its background tab opens until the daemon has it, so a worker that
// dies while the page loads leaves the capture to the next hello's backlog.

import { capturesFromTab, capturesInBackground, type Settings } from '../domain/settings.js';
import { NO_CAPTURE, type ExtensionCapture } from '../domain/capture.js';
import { folderPathOf, isPathInside, resolveFolderPath } from '../domain/paths.js';
import type { Bookmark, FolderPath, OwnedRoots, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { BookmarkEvent } from '../ports/bookmarkEvents.js';
import type { Clock } from '../ports/clock.js';
import type { ContentSourcePort } from '../ports/contentSource.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { Timer } from '../ports/timer.js';
import type { TransportPort } from '../ports/transport.js';
import { capture } from './capture.js';
import type { HelloOutcome } from './connection.js';
import { observeMove } from './observeMove.js';
import { sendTreeSnapshot } from './onConnected.js';
import { submitSave, type SubmittedSaves } from './submitSave.js';

// --- Constants ---

/** Quiet time after the last change under the owned roots before tree.snapshot is sent. */
export const SNAPSHOT_DEBOUNCE_MS = 2000;

/** At most this many saves are owed a background capture at once (the oldest is dropped past it). */
export const MAX_OWED_CAPTURES = 1000;

/** Open-tab capture is off: no tab is read. */
const NOTHING_OPEN: ContentSourcePort = { readTab: () => Promise.resolve(undefined) };

// --- Types ---

export interface TreeWatchDeps {
  readonly tree: BookmarkTreePort;
  readonly content: ContentSourcePort;
  readonly background: ContentSourcePort;
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly clock: Clock;
  readonly timer: Timer;
  readonly saves: SubmittedSaves;
  readonly storage: StoragePort;
}

/** What the runtime knows now that the events are judged against. */
export interface TreeWatchContext {
  followUp(): FolderPath | undefined;
  outcome(): HelloOutcome | undefined;
  settings(): Settings;
  /** True when the browser's report of this move is of a move the extension itself made (consumed). */
  isOwnMove(node_id: NodeId, parent_id: NodeId): boolean;
  track(work: Promise<unknown>): void;
  /** A debounced tree.snapshot was recorded by the daemon (it re-reads writer markers from it). */
  snapshotSent(): void;
}

// --- Pure helpers ---

function ownedPaths(context: TreeWatchContext): FolderPath[] {
  const roots: OwnedRoots | undefined = context.outcome()?.owned_roots;
  const followUp = context.followUp();
  return [
    ...(roots === undefined ? [] : [roots.follow_up, roots.dynomark, roots.graveyard]),
    ...(followUp === undefined ? [] : [followUp]),
  ];
}

function isOwnedFolder(tree: TreeRead, folderId: NodeId | null | undefined, context: TreeWatchContext): boolean {
  const path = folderId === null || folderId === undefined ? undefined : folderPathOf(tree, folderId);
  return path !== undefined && ownedPaths(context).some((root) => isPathInside(path, root));
}

function bookmarkOf(node: SnapshotNode, path: FolderPath): Bookmark | undefined {
  if (node.kind !== 'bookmark') return undefined;
  return { node_id: node.id, url: node.url, title: node.title, path, date_added: node.date_added };
}

// --- The watcher ---

export class TreeWatch {
  private cancelSnapshot: (() => void) | undefined;
  /** Saves that arrived while the role was unknown: the next backlog captures each once with the background chain allowed. Loaded once, then written through. */
  private owed: Promise<Set<NodeId>> | undefined;

  constructor(
    private readonly deps: TreeWatchDeps,
    private readonly context: TreeWatchContext,
  ) {}

  /** Act on one browser event. */
  async handle(event: BookmarkEvent): Promise<void> {
    const tree = await this.deps.tree.readTree();
    switch (event.kind) {
      case 'created':
        if (this.isFollowUp(tree, event.node.parent_id)) await this.save(event.node);
        return this.touched(tree, [event.node.parent_id]);
      case 'moved':
        return this.moved(tree, event.node_id, event.parent_id, event.old_parent_id);
      case 'changed':
        return this.touched(tree, [tree.nodes.find((n) => n.id === event.node_id)?.parent_id]);
      case 'removed':
        return this.touched(tree, [event.parent_id]);
      case 'reordered':
        return this.touched(tree, [event.folder_id]);
    }
  }

  /**
   * Ingest every bookmark now in Follow Up (after a full hello: repeats are
   * no-ops on the daemon). Open tabs only: the backlog is re-sent on every
   * hello, and a worker says hello often, so a background tab here would
   * reopen every waiting save each time; the created event carries the chain,
   * or, when it came while the role was unknown, this backlog does, once.
   */
  async submitBacklog(): Promise<void> {
    const path = this.context.followUp();
    if (path === undefined) return;
    const id = await this.deps.tree.resolveFolder(path);
    if (id === undefined) return;
    const children = await this.deps.tree.getChildren(id);
    const owed = await this.owedSet();
    const waiting = new Set(children.map((node) => node.id));
    const gone = [...owed].filter((node_id) => !waiting.has(node_id));
    for (const node_id of gone) owed.delete(node_id);
    if (gone.length > 0) await this.storeOwed(owed);
    for (const node of children) await this.save(node, { background: owed.has(node.id) });
  }

  // --- Flow ---

  private async moved(tree: TreeRead, node_id: NodeId, parent_id: NodeId, old_parent_id: NodeId): Promise<void> {
    const node = tree.nodes.find((n) => n.id === node_id);
    if (node !== undefined && this.isFollowUp(tree, parent_id) && !this.isFollowUp(tree, old_parent_id)) await this.save(node);
    await this.report(tree, node, parent_id, old_parent_id);
    this.touched(tree, [parent_id, old_parent_id]);
  }

  private async report(tree: TreeRead, node: SnapshotNode | undefined, parent_id: NodeId, old_parent_id: NodeId): Promise<void> {
    const outcome = this.context.outcome();
    const from = folderPathOf(tree, old_parent_id);
    const to = folderPathOf(tree, parent_id);
    const own = node !== undefined && this.context.isOwnMove(node.id, parent_id);
    if (outcome?.mode !== 'full' || node === undefined || from === undefined || to === undefined) return;
    // The node and its destination, not the node alone: a user move of a node the open batch names is still the user's.
    const in_flight = new Set<NodeId>(own ? [node.id] : []);
    await observeMove(
      { node_id: node.id, ...(node.kind === 'bookmark' ? { url: node.url } : {}), from, to },
      outcome.role,
      { owned_roots: outcome.owned_roots, in_flight },
      this.deps,
    );
  }

  private async save(node: SnapshotNode, options: { readonly background: boolean } = { background: true }): Promise<void> {
    const path = this.context.followUp();
    const bookmark = path === undefined ? undefined : bookmarkOf(node, path);
    if (bookmark === undefined) return;
    // No hello yet: the role that decides the chain is unknown, and the full hello's backlog will submit it.
    if (options.background && this.context.outcome() === undefined) return this.owe(bookmark.node_id);
    const submitted = this.deps.saves.get(bookmark.node_id, bookmark.url)?.outcome !== undefined;
    // A frame already sent and not answered is re-sent as it was: its capture is not taken again.
    const kept = submitted ? undefined : await this.deps.saves.recall(bookmark.node_id, bookmark.url);
    const content = submitted ? NO_CAPTURE : (kept ?? (await this.captureOf(bookmark, options.background)));
    await submitSave(bookmark, content, { ...this.deps, track: (work) => this.context.track(work) });
    // Paid only once the daemon has the save: a worker that dies first owes it still.
    const owed = await this.owedSet();
    if (owed.delete(bookmark.node_id)) await this.storeOwed(owed);
  }

  /** The saves owed a background capture, read from storage once per worker; every caller mutates this one set in place. */
  private owedSet(): Promise<Set<NodeId>> {
    this.owed ??= this.deps.storage.loadOwedCaptures().then(
      (node_ids) => new Set(node_ids ?? []),
      (error: unknown) => {
        this.owed = undefined;
        throw error;
      },
    );
    return this.owed;
  }

  /** Owe `node_id` a background capture, durably; the oldest debt is dropped past the bound. */
  private async owe(node_id: NodeId): Promise<void> {
    const owed = await this.owedSet();
    if (owed.has(node_id)) return;
    owed.add(node_id);
    for (const oldest of [...owed].slice(0, Math.max(0, owed.size - MAX_OWED_CAPTURES))) owed.delete(oldest);
    return this.storeOwed(owed);
  }

  /** Store the owed set as it is now: writes go out in call order, each carrying the whole set. */
  private storeOwed(owed: ReadonlySet<NodeId>): Promise<void> {
    return this.deps.storage.saveOwedCaptures([...owed]);
  }

  /**
   * The capture chain the settings and role allow: open tab (setting),
   * background tab (writer, setting), else none. When the chain may reach a
   * background tab the save is owed its capture first (paid once the daemon
   * has the save): a worker that dies while the page loads leaves it owed.
   */
  private async captureOf(bookmark: Bookmark, allowBackground: boolean): Promise<ExtensionCapture> {
    const settings = this.context.settings();
    const writer = this.context.outcome()?.role === 'writer';
    const background = allowBackground && writer && capturesInBackground(settings) ? this.deps.background : undefined;
    const content = capturesFromTab(settings) ? this.deps.content : NOTHING_OPEN;
    if (content === NOTHING_OPEN && background === undefined) return NO_CAPTURE;
    if (background === undefined) return capture(bookmark, { content });
    await this.owe(bookmark.node_id);
    return capture(bookmark, { content, background });
  }

  /** Schedule one tree.snapshot when any of these folders lies under an owned root (full connections only). */
  private touched(tree: TreeRead, folders: readonly (NodeId | null | undefined)[]): void {
    if (this.context.outcome()?.mode !== 'full') return;
    if (!folders.some((f) => isOwnedFolder(tree, f, this.context))) return;
    this.cancelSnapshot?.();
    this.cancelSnapshot = this.deps.timer.after(SNAPSHOT_DEBOUNCE_MS, () => {
      this.cancelSnapshot = undefined;
      this.context.track(sendTreeSnapshot(this.deps).then(() => this.context.snapshotSent()));
    });
  }

  private isFollowUp(tree: TreeRead, folderId: NodeId | null): boolean {
    const path = this.context.followUp();
    return folderId !== null && path !== undefined && resolveFolderPath(tree, path) === folderId;
  }
}
