/// <reference types="chrome" />
// backgroundTab.ts -- the writer's third ContentSourcePort (design, Future
// Considerations "Background-tab capture (MVP)"; task-031): open the saved URL
// in a background tab of an unfocused, minimized window, wait for it to load
// (up to a timeout), read it as from any tab (readPage, the open-tab
// adapter's extraction), and close the window whatever happened. The
// writer's browser is usually signed in to the same sites, so this recovers
// logged-in content for saves made on a reader device or a phone. One capture
// runs at a time: a burst of synced saves opens one window after another.

import type { TabContent } from '../../domain/capture.js';
import type { Url } from '../../domain/values.js';
import type { ContentSourcePort } from '../../ports/contentSource.js';
import type { Timer } from '../../ports/timer.js';
import { SystemTimer } from '../timer.js';
import { MAX_PAGE_UNITS, isPageText, readPage, type ScriptingApi } from './tabContent.js';

// --- Types ---

/** The part of chrome.windows this adapter uses. */
export interface BackgroundWindowsApi {
  create(data: {
    url: string;
    focused: boolean;
    state: 'minimized';
  }): Promise<{ id?: number | undefined; tabs?: { id?: number | undefined }[] | undefined } | undefined>;
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

// --- The adapter ---

export class ChromeBackgroundTab implements ContentSourcePort {
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly windows: BackgroundWindowsApi = chrome.windows,
    private readonly tabs: BackgroundTabsApi = chrome.tabs,
    private readonly scripting: ScriptingApi = chrome.scripting,
    private readonly timer: Timer = new SystemTimer(),
  ) {}

  /** Load `url` in a background tab and read it; undefined when it does not load in time or cannot be read. Never throws. */
  readTab(url: Url): Promise<TabContent | undefined> {
    const run = this.tail.then(() => this.capture(url));
    this.tail = run;
    return run;
  }

  private async capture(url: Url): Promise<TabContent | undefined> {
    let windowId: number | undefined;
    try {
      const opened = await this.windows.create({ url, focused: false, state: 'minimized' });
      windowId = opened?.id;
      const tabId = opened?.tabs?.[0]?.id;
      if (tabId === undefined || !(await this.loaded(tabId))) return undefined;
      const [frame] = await this.scripting.executeScript({ target: { tabId }, func: readPage, args: [MAX_PAGE_UNITS] });
      const page = frame?.result;
      return isPageText(page) && page.text.trim() !== '' ? { title: page.title, text: page.text } : undefined;
    } catch {
      return undefined;
    } finally {
      if (windowId !== undefined) await this.windows.remove(windowId).catch(() => undefined);
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
