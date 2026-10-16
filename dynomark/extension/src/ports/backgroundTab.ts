// backgroundTab.ts -- the writer's background-tab port (design, Future
// Considerations "Background-tab capture (MVP)"; Key Decisions "Background-tab
// capture" 2026-10-16): load a URL in a background tab with the browser's
// session and read it. The use case vets the URL with the daemon before the
// load and vets where the load ended after it (issue #534); the adapter
// blocks, by literal, every hop to a private host when asked to, before that
// hop loads.

import type { TabContent } from '../domain/capture.js';
import type { Url } from '../domain/values.js';

// --- Types ---

/** How a background load is guarded. */
export interface BackgroundLoad {
  /** True: no hop of the load (a redirect included) may reach a loopback, private, link-local or local-name host. */
  readonly blockPrivateHosts: boolean;
}

/** What a background tab yields: the page's readable text and title, and the URL the page was read at (after any redirect). */
export interface LoadedPage extends TabContent {
  readonly url: Url;
}

export interface BackgroundTabPort {
  /** Load `url` in a background tab and read it; undefined when it does not load, is blocked or cannot be read. Never throws for those. */
  readTab(url: Url, load: BackgroundLoad): Promise<LoadedPage | undefined>;
}
