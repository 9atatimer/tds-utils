// treeWatch.ts -- what each bookmark event means (design, "The extension":
// Watch Follow Up, Capture from the open tab, Record feedback; contract v1
// README, "Connection lifecycle", steps 5 and 6). A bookmark created in, or
// moved into, Follow Up is captured and ingested; a move is reported as
// move.observed when both ends are owned; a change under the owned roots
// schedules one debounced tree.snapshot. Every step is short and repeatable:
// the worker can die between any two events, and ingest is idempotent.

import { capturesFromTab, type Settings } from '../domain/settings.js';
import { NO_CAPTURE } from '../domain/capture.js';
import { folderPathOf, isPathInside, resolveFolderPath } from '../domain/paths.js';
import type { Bookmark, FolderPath, OwnedRoots, SnapshotNode, TreeRead } from '../domain/tree.js';
import type { NodeId } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { BookmarkEvent } from '../ports/bookmarkEvents.js';
import type { Clock } from '../ports/clock.js';
import type { ContentSourcePort } from '../ports/contentSource.js';
import type { IdSource } from '../ports/idSource.js';
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

// --- Types ---

export interface TreeWatchDeps {
  readonly tree: BookmarkTreePort;
  readonly content: ContentSourcePort;
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly clock: Clock;
  readonly timer: Timer;
  readonly saves: SubmittedSaves;
}

/** What the runtime knows now that the events are judged against. */
export interface TreeWatchContext {
  followUp(): FolderPath | undefined;
  outcome(): HelloOutcome | undefined;
  settings(): Settings;
  /** True when the browser's report of this move is of a move the extension itself made (consumed). */
  isOwnMove(node_id: NodeId, parent_id: NodeId): boolean;
  /** The nodes the open batch names. */
  inFlight(): ReadonlySet<NodeId>;
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

  /** Ingest every bookmark now in Follow Up (after a full hello: repeats are no-ops on the daemon). */
  async submitBacklog(): Promise<void> {
    const path = this.context.followUp();
    if (path === undefined) return;
    const id = await this.deps.tree.resolveFolder(path);
    if (id === undefined) return;
    for (const node of await this.deps.tree.getChildren(id)) await this.save(node);
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
    const in_flight = new Set([...this.context.inFlight(), ...(own ? [node.id] : [])]);
    await observeMove(
      { node_id: node.id, ...(node.kind === 'bookmark' ? { url: node.url } : {}), from, to },
      outcome.role,
      { owned_roots: outcome.owned_roots, in_flight },
      this.deps,
    );
  }

  private async save(node: SnapshotNode): Promise<void> {
    const path = this.context.followUp();
    const bookmark = path === undefined ? undefined : bookmarkOf(node, path);
    if (bookmark === undefined) return;
    const content = capturesFromTab(this.context.settings()) ? await capture(bookmark, this.deps) : NO_CAPTURE;
    await submitSave(bookmark, content, this.deps);
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
