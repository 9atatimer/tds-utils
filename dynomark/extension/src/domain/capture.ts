// capture.ts -- page content for a bookmark (design, "Capture"), and the rules
// for turning what an open tab shows into one.

import { MAX_CAPTURE_TEXT, MAX_TITLE, fitText } from './limits.js';
import type { Title, Url } from './values.js';

// --- Types ---

/** Where a capture's text came from. `fetch` is the daemon's alone; the extension sends `tab`, `background_tab` or `none`. */
export type CaptureSource = 'tab' | 'background_tab' | 'fetch' | 'none';

/** Readable text plus title for a bookmark. `none` carries empty text. */
export interface Capture {
  readonly source: CaptureSource;
  readonly text: string;
  readonly title?: Title;
}

/** A source the extension itself can send: never `fetch`. */
export type ExtensionCaptureSource = Exclude<CaptureSource, 'fetch'>;

/** A capture as the extension sends it in `ingest`. */
export interface ExtensionCapture extends Capture {
  readonly source: ExtensionCaptureSource;
}

/** What an open tab showing a URL yields: readable text already extracted by the content adapter, and the page title. */
export interface TabContent {
  readonly title: Title;
  readonly text: string;
}

// --- Constants ---

/** No content was read: the daemon falls back to fetch. */
export const NO_CAPTURE: ExtensionCapture = { source: 'none', text: '' };

const CAPTURABLE_SCHEME = /^https?:/i;

// --- Predicates ---

/** True only for http(s) URLs: nothing else is ever read from a page (design, Security). */
export function isCapturableUrl(url: Url): boolean {
  return CAPTURABLE_SCHEME.test(url);
}

/** True when the extension may send this capture: any source but the daemon's own `fetch`. */
export function isExtensionCapture(capture: Capture): capture is ExtensionCapture {
  return capture.source !== 'fetch';
}

// --- Pure helpers ---

/** Where a page the extension read was showing: a tab the user had open, or one the writer opened in the background. */
export type PageSource = Extract<CaptureSource, 'tab' | 'background_tab'>;

/** A capture of what a page shows, within the caps and well-formed; `NO_CAPTURE` when it has no readable text. */
export function captureFromPage(page: TabContent, source: PageSource): ExtensionCapture {
  if (page.text.trim() === '') return NO_CAPTURE;
  return { source, text: fitText(page.text, MAX_CAPTURE_TEXT).text, title: fitText(page.title, MAX_TITLE).text };
}

/** A `tab` capture of what an open tab shows. */
export function captureFromTab(tab: TabContent): ExtensionCapture {
  return captureFromPage(tab, 'tab');
}
