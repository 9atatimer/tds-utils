// capture.ts -- use case "Content is captured from the open tab" (design,
// Behaviors and Interfaces): capture(bookmark, *, content) -> Capture. The
// only moment page content is read. On the writer the chain goes on to a
// background tab (design, Future Considerations "Background-tab capture
// (MVP)"): matching tab -> background tab -> none, and the daemon fetches
// what is left at none. A non-http(s) URL is never read.
//
// One address policy for both capture paths (Key Decisions "Background-tab
// capture", issue #410; issue #534): a background tab opens only for a URL the
// daemon vets; unless the daemon's policy allows private addresses (its
// opt-out), the tab blocks every hop to a private host by literal before it
// loads; and a page read anywhere but the vetted URL (a redirect) is kept only
// when the daemon allows where it ended. A refusal, or a vet that cannot be
// answered, captures nothing.

import { NO_CAPTURE, PRIVATE_ADDRESS_PROBE, captureFromPage, isCapturableUrl, type ExtensionCapture } from '../domain/capture.js';
import type { Bookmark } from '../domain/tree.js';
import type { Url } from '../domain/values.js';
import type { BackgroundTabPort } from '../ports/backgroundTab.js';
import type { ContentSourcePort } from '../ports/contentSource.js';

// --- Types ---

/** The background-tab link of the chain: the tab adapter, and the daemon's vet every URL passes before a tab opens. */
export interface BackgroundCapture {
  /** Opens the URL in a background tab and reads it. */
  readonly tabs: BackgroundTabPort;
  /** True only when the daemon allows the URL (url.vet); false or a rejection never opens the tab. */
  vet(url: Url): Promise<boolean>;
}

export interface CaptureDeps {
  /** Reads a tab the user already has open on the URL. */
  readonly content: ContentSourcePort;
  /** Present only when the chain includes a background tab (writer, setting on). */
  readonly background?: BackgroundCapture;
}

// --- Flow ---

/** Whether the daemon allows a background tab to load `url`: an error or a lost link is a refusal. */
async function isVetted(url: Url, background: BackgroundCapture): Promise<boolean> {
  try {
    return await background.vet(url);
  } catch {
    return false;
  }
}

/** The background tab's capture of a URL the daemon vetted: guarded by the daemon's policy, and kept only where it ended allowed. */
async function captureInBackground(url: Url, background: BackgroundCapture): Promise<ExtensionCapture> {
  const blockPrivateHosts = !(await isVetted(PRIVATE_ADDRESS_PROBE, background));
  const page = await background.tabs.readTab(url, { blockPrivateHosts });
  if (page === undefined) return NO_CAPTURE;
  if (page.url !== url && !(await isVetted(page.url, background))) return NO_CAPTURE;
  return captureFromPage(page, 'background_tab');
}

/** The saved page's content: from a tab showing exactly its URL, else from a background tab the daemon vetted, else `source: none`. */
export async function capture(bookmark: Bookmark, deps: CaptureDeps): Promise<ExtensionCapture> {
  if (!isCapturableUrl(bookmark.url)) return NO_CAPTURE;
  const tab = await deps.content.readTab(bookmark.url);
  const fromTab = tab === undefined ? NO_CAPTURE : captureFromPage(tab, 'tab');
  if (fromTab.source !== 'none' || deps.background === undefined) return fromTab;
  if (!(await isVetted(bookmark.url, deps.background))) return NO_CAPTURE;
  return captureInBackground(bookmark.url, deps.background);
}
