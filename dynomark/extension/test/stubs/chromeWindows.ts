// chromeWindows.ts -- tiny chrome.windows, chrome.tabs and chrome.scripting
// stand-ins for the background-tab adapter: a window opened on a URL holds
// one tab that finishes loading (or never does), and injecting into it
// returns the page served for that URL, or throws as Chrome does for a page
// it will not script. Every call is logged in order.

import type { PageText } from '../../src/adapters/chrome/tabContent.js';

type Served = PageText | 'unreadable' | 'never-loads';

interface StubWindow {
  readonly tabId: number;
  readonly url: string;
  readonly state: string;
}

export class BackgroundBrowserStub {
  /** Every call, in order: `open <url> focused=<b> state=<s>`, `inject <url>`, `close <url>`. */
  readonly log: string[] = [];
  /** When set, the next windows.create rejects. */
  refuseWindows = false;
  private readonly pages = new Map<string, Served>();
  private readonly open = new Map<number, StubWindow>();
  private next = 100;

  /** What a tab loading `url` shows. A URL never served loads to an unreadable error page. */
  serve(url: string, page: Served): void {
    this.pages.set(url, page);
  }

  /** How many windows are open now. */
  openWindows(): number {
    return this.open.size;
  }

  readonly windows = {
    create: (data: { url: string; focused: boolean; state: string }): Promise<{ id?: number; tabs?: { id?: number }[] }> => {
      if (this.refuseWindows) return Promise.reject(new Error('No current window'));
      this.next += 2;
      const id = this.next;
      this.open.set(id, { tabId: id + 1, url: data.url, state: data.state });
      this.log.push(`open ${data.url} focused=${String(data.focused)} state=${data.state}`);
      return Promise.resolve({ id, tabs: [{ id: id + 1 }] });
    },
    get: (windowId: number, _options: { populate: true }): Promise<{ state?: string; tabs?: { id?: number }[] }> => {
      const win = this.open.get(windowId);
      if (win === undefined) return Promise.reject(new Error(`No window with id: ${windowId}.`));
      return Promise.resolve({ state: win.state, tabs: [{ id: win.tabId }] });
    },
    remove: (windowId: number): Promise<void> => {
      const win = this.open.get(windowId);
      this.open.delete(windowId);
      this.log.push(`close ${win?.url ?? String(windowId)}`);
      return Promise.resolve();
    },
  };

  readonly tabs = {
    get: (tabId: number): Promise<{ status?: string; url?: string }> => {
      const win = this.byTab(tabId);
      if (win === undefined) return Promise.reject(new Error(`No tab with id: ${tabId}.`));
      return Promise.resolve({ status: this.pages.get(win.url) === 'never-loads' ? 'loading' : 'complete', url: win.url });
    },
  };

  readonly scripting = {
    executeScript: (injection: { target: { tabId: number } }): Promise<readonly { result?: unknown }[]> => {
      const win = this.byTab(injection.target.tabId);
      if (win === undefined) return Promise.reject(new Error(`No tab with id: ${injection.target.tabId}.`));
      this.log.push(`inject ${win.url}`);
      const page = this.pages.get(win.url);
      if (page === undefined || typeof page === 'string') {
        return Promise.reject(new Error('Cannot access contents of url "chrome-error://chromewebdata/".'));
      }
      return Promise.resolve([{ result: { ...page } }]);
    },
  };

  private byTab(tabId: number): StubWindow | undefined {
    return [...this.open.values()].find((w) => w.tabId === tabId);
  }
}
