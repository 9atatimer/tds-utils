/// <reference types="chrome" />
// bookmarkEvents.ts -- chrome.bookmarks events as BookmarkEvents (design,
// "The extension": Watch Follow Up on onCreated/onMoved; Record feedback on
// every onMoved; snapshots after changes). Listeners are added synchronously
// when called, so the service worker's top-level code registers them before
// its first await (MV3 delivers the waking event only to listeners added
// then).

import type { BookmarkEvent } from '../../ports/bookmarkEvents.js';
import { toSnapshotNode, type ChromeBookmarkNode } from './bookmarkTree.js';

// --- Types ---

interface EventLike<A extends unknown[]> {
  addListener(callback: (...args: A) => void): void;
}

/** The chrome.bookmarks events this adapter listens to. */
export interface BookmarkEventsApi {
  readonly onCreated: EventLike<[string, ChromeBookmarkNode]>;
  readonly onMoved: EventLike<[string, { parentId: string; oldParentId: string }]>;
  readonly onChanged: EventLike<[string, unknown]>;
  readonly onRemoved: EventLike<[string, { parentId: string }]>;
  readonly onChildrenReordered: EventLike<[string, unknown]>;
}

// --- Entry ---

/** Report every bookmark change to `listener`. */
export function listenBookmarkEvents(listener: (event: BookmarkEvent) => void, api: BookmarkEventsApi = chrome.bookmarks): void {
  api.onCreated.addListener((_id, node) => listener({ kind: 'created', node: toSnapshotNode(node) }));
  api.onMoved.addListener((id, info) =>
    listener({ kind: 'moved', node_id: id, parent_id: info.parentId, old_parent_id: info.oldParentId }),
  );
  api.onChanged.addListener((id) => listener({ kind: 'changed', node_id: id }));
  api.onRemoved.addListener((id, info) => listener({ kind: 'removed', node_id: id, parent_id: info.parentId }));
  api.onChildrenReordered.addListener((id) => listener({ kind: 'reordered', folder_id: id }));
}
