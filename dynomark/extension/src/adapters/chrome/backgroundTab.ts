/// <reference types="chrome" />
// backgroundTab.ts -- the writer's third ContentSourcePort (design, Future
// Considerations "Background-tab capture (MVP)"; task-031): open the saved URL
// in a background tab of an unfocused, minimized window, wait for it to load
// (up to a timeout), read it as from any tab (readPage, the open-tab
// adapter's extraction), and close the window whatever happened. The
// writer's browser is usually signed in to the same sites, so this recovers
// logged-in content for saves made on a reader device or a phone. One capture
// runs at a time: a burst of synced saves opens one window after another.
//
// A worker terminated while the page loads never reaches the close, so the
// open window is recorded in extension storage (key `capture_window`) until
// it is closed, and the next worker's sweep() closes it -- only when that id
// still names a minimized window holding the one tab it opened.

import type { TabContent } from '../../domain/capture.js';
import type { Url } from '../../domain/values.js';
import type { ContentSourcePort } from '../../ports/contentSource.js';
import type { Timer } from '../../ports/timer.js';
import { SystemTimer } from '../timer.js';
import type { StorageAreaApi } from './storage.js';
import { MAX_PAGE_UNITS, isPageText, readPage, type ScriptingApi } from './tabContent.js';

// --- Types ---

/** The part of chrome.windows this adapter uses. */
export interface BackgroundWindowsApi {
  create(data: {
    url: string;
    focused: boolean;
    state: 'minimized';
  }): Promise<{ id?: number | undefined; tabs?: { id?: number | undefined }[] | undefined } | undefined>;
  get(
    windowId: number,
    options: { populate: true },
  ): Promise<{ state?: string | undefined; tabs?: { id?: number | undefined }[] | undefined }>;
  remove(windowId: number): Promise<void>;
}

/** The part of chrome.tabs this adapter uses. */
export interface BackgroundTabsApi {
  get(tabId: number): Promise<{ status?: string | undefined }>;
}

// --- Constants ---

/** How long a background page may take to load before it is given up (the daemon then fetches). */
export const BACKGROUND_LOAD_TIMEOUT_MS = 20_000;
/** How often the tab's load status is checked. */
const POLL_MS = 250;
/** The storage key of the window a capture has open. */
const OPEN_WINDOW_KEY = 'capture_window';

// --- Types (stored) ---

/** The window a capture opened and has not closed yet. */
interface OpenWindow {
  readonly window_id: number;
  readonly tab_id: number;
}

function isOpenWindow(value: unknown): value is OpenWindow {
  const v = value as Partial<OpenWindow> | undefined;
  return typeof v?.window_id === 'number' && typeof v.tab_id === 'number';
}

// --- The adapter ---

export class ChromeBackgroundTab implements ContentSourcePort {
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly windows: BackgroundWindowsApi = chrome.windows,
    private readonly tabs: BackgroundTabsApi = chrome.tabs,
    private readonly scripting: ScriptingApi = chrome.scripting,
    private readonly timer: Timer = new SystemTimer(),
    private readonly store: StorageAreaApi = chrome.storage.local,
  ) {}

  /** Load `url` in a background tab and read it; undefined when it does not load in time or cannot be read. Never throws. */
  readTab(url: Url): Promise<TabContent | undefined> {
    const run = this.tail.then(() => this.capture(url));
    this.tail = run;
    return run;
  }

  /** Close the window an earlier worker's capture left open, if it is still that window. Never throws; captures wait for it. */
  sweep(): Promise<void> {
    const run = this.tail.then(() => this.closeLeftOpen());
    this.tail = run;
    return run;
  }

  private async capture(url: Url): Promise<TabContent | undefined> {
    let windowId: number | undefined;
    try {
      const opened = await this.windows.create({ url, focused: false, state: 'minimized' });
      windowId = opened?.id;
      const tabId = opened?.tabs?.[0]?.id;
      if (windowId !== undefined && tabId !== undefined) await this.remember({ window_id: windowId, tab_id: tabId });
      if (tabId === undefined || !(await this.loaded(tabId))) return undefined;
      const [frame] = await this.scripting.executeScript({ target: { tabId }, func: readPage, args: [MAX_PAGE_UNITS] });
      const page = frame?.result;
      return isPageText(page) && page.text.trim() !== '' ? { title: page.title, text: page.text } : undefined;
    } catch {
      return undefined;
    } finally {
      if (windowId !== undefined) await this.close(windowId);
    }
  }

  private async closeLeftOpen(): Promise<void> {
    try {
      const left = (await this.store.get(OPEN_WINDOW_KEY))[OPEN_WINDOW_KEY];
      if (!isOpenWindow(left)) return;
      const win = await this.windows.get(left.window_id, { populate: true }).catch(() => undefined);
      const tabs = win?.tabs ?? [];
      const ours = win?.state === 'minimized' && tabs.length === 1 && tabs[0]?.id === left.tab_id;
      if (ours) await this.close(left.window_id);
      else await this.store.remove(OPEN_WINDOW_KEY);
    } catch {
      return;
    }
  }

  private remember(open: OpenWindow): Promise<void> {
    return this.store.set({ [OPEN_WINDOW_KEY]: open });
  }

  /** Close the window, then forget it (a close that fails leaves it recorded for the next sweep). */
  private async close(windowId: number): Promise<void> {
    try {
      await this.windows.remove(windowId);
      await this.store.remove(OPEN_WINDOW_KEY);
    } catch {
      return;
    }
  }

  /** True once the tab reports its load complete; false at the timeout. */
  private async loaded(tabId: number): Promise<boolean> {
    for (let waited = 0; ; waited += POLL_MS) {
      if ((await this.tabs.get(tabId)).status === 'complete') return true;
      if (waited >= BACKGROUND_LOAD_TIMEOUT_MS) return false;
      await new Promise<void>((resolve) => this.timer.after(POLL_MS, resolve));
    }
  }
}
