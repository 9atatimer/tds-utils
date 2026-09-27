// chromeTabs.ts -- tiny chrome.tabs and chrome.scripting stand-ins. A tab
// shows a URL; injecting into it returns the page it was opened with (the
// injected extraction itself runs only in a real browser, test/integration),
// or throws as Chrome does for a page it will not script.

import type { PageText, ScriptingApi, TabsApi } from '../../src/adapters/chrome/tabContent.js';

interface StubTab {
  readonly id: number;
  readonly url: string;
  readonly lastAccessed: number;
  readonly page: PageText | 'unreadable';
}

export class TabsStub implements TabsApi, ScriptingApi {
  private readonly tabs: StubTab[] = [];
  /** Every tab id a script was injected into, in order. */
  readonly injected: number[] = [];

  /** Open a tab on `url`; `lastAccessed` orders tabs showing one URL. */
  open(url: string, page: PageText | 'unreadable', lastAccessed = this.tabs.length): number {
    const id = this.tabs.length + 1;
    this.tabs.push({ id, url, lastAccessed, page });
    return id;
  }

  query(): Promise<{ id?: number; url?: string; lastAccessed?: number }[]> {
    return Promise.resolve(this.tabs.map(({ id, url, lastAccessed }) => ({ id, url, lastAccessed })));
  }

  executeScript(injection: { target: { tabId: number } }): Promise<{ result?: unknown }[]> {
    const tab = this.tabs.find((t) => t.id === injection.target.tabId);
    this.injected.push(injection.target.tabId);
    if (tab === undefined) return Promise.reject(new Error(`No tab with id: ${injection.target.tabId}.`));
    if (tab.page === 'unreadable') return Promise.reject(new Error('Cannot access contents of url "chrome-error://chromewebdata/".'));
    return Promise.resolve([{ result: { ...tab.page } }]);
  }
}
