// bookmarkEvents.ts -- Firefox's browser.bookmarks events as BookmarkEvents
// (task-032): the same events as Chrome's, read with Firefox's node dialect
// (a separator stays a separator). Firefox has no onChildrenReordered; it
// reports a reorder as moves. Listeners are added synchronously when called,
// so the background script registers them before its first await.

import type { BookmarkEvent } from '../../ports/bookmarkEvents.js';
import { forwardBookmarkEvents, type BookmarkEventsApi } from '../chrome/bookmarkEvents.js';
import { toFirefoxSnapshotNode, type FirefoxBookmarkNode } from './bookmarkTree.js';

// --- Types ---

/** The browser.bookmarks events this adapter listens to. */
export type FirefoxBookmarkEventsApi = BookmarkEventsApi<FirefoxBookmarkNode>;

// --- Entry ---

/** Report every browser.bookmarks change to `listener`. */
export function listenFirefoxBookmarkEvents(listener: (event: BookmarkEvent) => void, api: FirefoxBookmarkEventsApi): void {
  forwardBookmarkEvents(listener, api, toFirefoxSnapshotNode);
}
