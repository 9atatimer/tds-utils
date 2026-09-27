// capture.ts -- use case "Content is captured from the open tab" (design,
// Behaviors and Interfaces): capture(bookmark, *, content) -> Capture. The
// only moment page content is read. On the writer the chain goes on to a
// background tab (design, Future Considerations "Background-tab capture
// (MVP)"): matching tab -> background tab -> none, and the daemon fetches
// what is left at none. A non-http(s) URL is never read.

import { NO_CAPTURE, captureFromPage, isCapturableUrl, type ExtensionCapture } from '../domain/capture.js';
import type { Bookmark } from '../domain/tree.js';
import type { ContentSourcePort } from '../ports/contentSource.js';

// --- Types ---

export interface CaptureDeps {
  /** Reads a tab the user already has open on the URL. */
  readonly content: ContentSourcePort;
  /** Opens the URL in a background tab and reads it; present only when the chain includes it (writer, setting on). */
  readonly background?: ContentSourcePort;
}

// --- Flow ---

/** The saved page's content: from a tab showing exactly its URL, else from a background tab when allowed, else `source: none`. */
export async function capture(bookmark: Bookmark, deps: CaptureDeps): Promise<ExtensionCapture> {
  if (!isCapturableUrl(bookmark.url)) return NO_CAPTURE;
  const tab = await deps.content.readTab(bookmark.url);
  const fromTab = tab === undefined ? NO_CAPTURE : captureFromPage(tab, 'tab');
  if (fromTab.source !== 'none' || deps.background === undefined) return fromTab;
  const page = await deps.background.readTab(bookmark.url);
  return page === undefined ? NO_CAPTURE : captureFromPage(page, 'background_tab');
}
