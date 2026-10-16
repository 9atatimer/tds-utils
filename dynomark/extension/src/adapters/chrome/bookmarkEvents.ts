/// <reference types="chrome" />
// bookmarkEvents.ts -- chrome.bookmarks events as BookmarkEvents (design,
// "The extension": Watch Follow Up on onCreated/onMoved; Record feedback on
// every onMoved; snapshots after changes). Listeners are added synchronously
// when called, so the service worker's top-level code registers them before
// its first await (MV3 delivers the waking event only to listeners added
// then). Firefox's events have the same shape (adapters/firefox/
// bookmarkEvents.ts passes its own node reading and has no
// onChildrenReordered).

import type { SnapshotNode } from '../../domain/tree.js';
import type { BookmarkEvent } from '../../ports/bookmarkEvents.js';
import { toSnapshotNode, type ChromeBookmarkNode } from './bookmarkTree.js';

// --- Types ---

interface EventLike<A extends unknown[]> {
  addListener(callback: (...args: A) => void): void;
}

/** The bookmarks events this adapter listens to, over the browser's node shape N. */
export interface BookmarkEventsApi<N = ChromeBookmarkNode> {
  readonly onCreated: EventLike<[string, N]>;
  readonly onMoved: EventLike<[string, { parentId: string; oldParentId: string }]>;
  readonly onChanged: EventLike<[string, unknown]>;
  readonly onRemoved: EventLike<[string, { parentId: string }]>;
  /** Absent in Firefox, which reports a reorder as moves. */
  readonly onChildrenReordered?: EventLike<[string, unknown]>;
}

// --- Entry ---

/** Report every bookmark change to `listener`, reading the browser's nodes with `toNode` (shared with Firefox). */
export function forwardBookmarkEvents<N>(
  listener: (event: BookmarkEvent) => void,
  api: BookmarkEventsApi<N>,
  toNode: (node: N) => SnapshotNode,
): void {
  api.onCreated.addListener((_id, node) => listener({ kind: 'created', node: toNode(node) }));
  // A move within one folder is a reorder (Chrome on a drag, Firefox always): never move feedback.
  api.onMoved.addListener((id, info) =>
    listener(
      info.parentId === info.oldParentId
        ? { kind: 'reordered', folder_id: info.parentId }
        : { kind: 'moved', node_id: id, parent_id: info.parentId, old_parent_id: info.oldParentId },
    ),
  );
  api.onChanged.addListener((id) => listener({ kind: 'changed', node_id: id }));
  api.onRemoved.addListener((id, info) => listener({ kind: 'removed', node_id: id, parent_id: info.parentId }));
  api.onChildrenReordered?.addListener((id) => listener({ kind: 'reordered', folder_id: id }));
}

/** Report every chrome.bookmarks change to `listener`. */
export function listenBookmarkEvents(listener: (event: BookmarkEvent) => void, api: BookmarkEventsApi = chrome.bookmarks): void {
  forwardBookmarkEvents(listener, api, toSnapshotNode);
}
