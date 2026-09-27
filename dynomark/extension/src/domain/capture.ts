// capture.ts -- page content for a bookmark (design, "Capture").

import type { Title } from './values.js';

/** Where a capture's text came from. `fetch` is the daemon's alone; the extension sends `tab`, `background_tab` or `none`. */
export type CaptureSource = 'tab' | 'background_tab' | 'fetch' | 'none';

/** Readable text plus title for a bookmark. `none` carries empty text. */
export interface Capture {
  readonly source: CaptureSource;
  readonly text: string;
  readonly title?: Title;
}

/** What an open tab showing a URL yields: readable text already extracted by the content adapter, and the page title. */
export interface TabContent {
  readonly title: Title;
  readonly text: string;
}
