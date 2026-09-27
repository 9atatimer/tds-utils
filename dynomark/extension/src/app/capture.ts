// capture.ts -- use case "Content is captured from the open tab" (design,
// Behaviors and Interfaces): capture(bookmark, *, content) -> Capture. The
// only moment page content is read; a URL the tab adapter cannot show, or a
// non-http(s) URL, yields source none and the daemon falls back to fetch.

import { NO_CAPTURE, captureFromTab, isCapturableUrl, type Capture } from '../domain/capture.js';
import type { Bookmark } from '../domain/tree.js';
import type { ContentSourcePort } from '../ports/contentSource.js';

// --- Flow ---

/** The saved page's content from a tab showing exactly its URL, else `source: none`. */
export async function capture(bookmark: Bookmark, deps: { readonly content: ContentSourcePort }): Promise<Capture> {
  if (!isCapturableUrl(bookmark.url)) return NO_CAPTURE;
  const tab = await deps.content.readTab(bookmark.url);
  return tab === undefined ? NO_CAPTURE : captureFromTab(tab);
}
