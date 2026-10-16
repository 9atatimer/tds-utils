// chromeWindows.ts -- tiny chrome.windows, chrome.tabs, chrome.scripting and
// chrome.declarativeNetRequest stand-ins for the background-tab adapter: a
// window opened on a URL holds one tab that finishes loading (or never does),
// a tab can be navigated, a navigation follows the redirects served for it,
// and a session block rule scoped to the tab stops a main-frame hop whose URL
// its regexFilter matches (the hop shows an error page, as Chrome's does).
// Injecting into a tab returns the page served for the URL it shows, with
// that URL as location.href, or throws as Chrome does for a page it will not
// script (a blocked tab shows, and is logged as, Chrome's error page). Every call is logged in order.

import type { PageText } from '../../src/adapters/chrome/tabContent.js';

type Served = PageText | 'unreadable' | 'never-loads';

/** The document a tab shows when a block rule stopped its navigation. */
const BLOCKED_PAGE = 'chrome-error://chromewebdata/';

interface StubTab {
  readonly tabId: number;
  readonly state: string;
  url: string;
  /** The navigation was stopped by a block rule: the tab shows an error page. */
  blocked: boolean;
}

/** A session rule as the adapter installs it. */
export interface StubRule {
  readonly id: number;
  readonly action: { readonly type: string };
  readonly condition: { readonly regexFilter?: string; readonly tabIds?: readonly number[]; readonly resourceTypes?: readonly string[] };
}

export class BackgroundBrowserStub {
  /** Every call, in order: `open <url> focused=<b> state=<s>`, `navigate <url>`, `blocked <url>`, `inject <url>`, `close <url>`. */
  readonly log: string[] = [];
  /** When set, the next windows.create rejects. */
  refuseWindows = false;
  /** When set, updateSessionRules rejects adding rules (an unsupported regex, or no permission). */
  refuseRules = false;
  private readonly pages = new Map<string, Served>();
  private readonly redirects = new Map<string, string>();
  private readonly open = new Map<number, StubTab>();
  private readonly rules = new Map<number, StubRule>();
  private next = 100;

  /** What a tab loading `url` shows. A URL never served loads to an unreadable error page. */
  serve(url: string, page: Served): void {
    this.pages.set(url, page);
  }

  /** Loading `from` answers a redirect to `to` (a 302). */
  redirect(from: string, to: string): void {
    this.redirects.set(from, to);
  }

  /** How many windows are open now. */
  openWindows(): number {
    return this.open.size;
  }

  /** The session rules installed now. */
  sessionRules(): StubRule[] {
    return [...this.rules.values()];
  }

  readonly windows = {
    create: (data: { url: string; focused: boolean; state: string }): Promise<{ id?: number; tabs?: { id?: number }[] }> => {
      if (this.refuseWindows) return Promise.reject(new Error('No current window'));
      this.next += 2;
      const id = this.next;
      const tab: StubTab = { tabId: id + 1, url: data.url, state: data.state, blocked: false };
      this.open.set(id, tab);
      this.log.push(`open ${data.url} focused=${String(data.focused)} state=${data.state}`);
      this.navigate(tab, data.url);
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
      const tab = this.byTab(tabId);
      if (tab === undefined) return Promise.reject(new Error(`No tab with id: ${tabId}.`));
      const loading = !tab.blocked && this.pages.get(tab.url) === 'never-loads';
      return Promise.resolve({ status: loading ? 'loading' : 'complete', url: tab.url });
    },
    update: (tabId: number, properties: { url: string }): Promise<unknown> => {
      const tab = this.byTab(tabId);
      if (tab === undefined) return Promise.reject(new Error(`No tab with id: ${tabId}.`));
      this.log.push(`navigate ${properties.url}`);
      this.navigate(tab, properties.url);
      return Promise.resolve({ id: tabId });
    },
  };

  readonly scripting = {
    executeScript: (injection: { target: { tabId: number } }): Promise<readonly { result?: unknown }[]> => {
      const tab = this.byTab(injection.target.tabId);
      if (tab === undefined) return Promise.reject(new Error(`No tab with id: ${injection.target.tabId}.`));
      this.log.push(`inject ${tab.blocked ? BLOCKED_PAGE : tab.url}`);
      const page = tab.blocked ? undefined : this.pages.get(tab.url);
      if (page === undefined || typeof page === 'string') {
        return Promise.reject(new Error('Cannot access contents of url "chrome-error://chromewebdata/".'));
      }
      return Promise.resolve([{ result: { ...page, url: tab.url } }]);
    },
  };

  readonly declarativeNetRequest = {
    updateSessionRules: (options: { removeRuleIds?: number[]; addRules?: StubRule[] }): Promise<void> => {
      if (this.refuseRules && (options.addRules?.length ?? 0) > 0)
        return Promise.reject(new Error('Rule with id 1 specifies an invalid regex'));
      for (const id of options.removeRuleIds ?? []) this.rules.delete(id);
      for (const rule of options.addRules ?? []) {
        if (this.rules.has(rule.id)) return Promise.reject(new Error(`Rule with id ${rule.id} does not have a unique ID.`));
        this.rules.set(rule.id, rule);
      }
      return Promise.resolve();
    },
  };

  /** Follow `url`'s redirects; a hop a block rule matches stops the navigation there. */
  private navigate(tab: StubTab, url: string): void {
    tab.blocked = false;
    for (let hop = url, seen = 0; seen < 20; seen += 1) {
      tab.url = hop;
      if (this.isBlocked(tab.tabId, hop)) {
        tab.blocked = true;
        this.log.push(`blocked ${hop}`);
        return;
      }
      const to = this.redirects.get(hop);
      if (to === undefined) return;
      hop = to;
    }
  }

  private isBlocked(tabId: number, url: string): boolean {
    return [...this.rules.values()].some(
      (rule) =>
        rule.action.type === 'block' &&
        (rule.condition.tabIds === undefined || rule.condition.tabIds.includes(tabId)) &&
        (rule.condition.resourceTypes?.includes('main_frame') ?? false) &&
        rule.condition.regexFilter !== undefined &&
        new RegExp(rule.condition.regexFilter, 'i').test(url),
    );
  }

  private byTab(tabId: number): StubTab | undefined {
    return [...this.open.values()].find((w) => w.tabId === tabId);
  }
}
