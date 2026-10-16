// firefoxBrowser.ts -- a stand-in for Firefox's `browser` namespace, built
// from the tiny per-API stubs: browser.bookmarks in Firefox's shapes, history,
// tabs and scripting (open tabs, plus the background-tab windows and their
// declarativeNetRequest session rules), storage,
// native messaging that reports a lost host on port.error, the sidebar, the
// omnibox and commands. Each part is exposed so a test can arrange and
// observe it.

import type { FirefoxBrowser } from '../../src/adapters/firefox/namespace.js';
import { EventStub } from './chromeEvents.js';
import { HistoryApiStub } from './chromeHistory.js';
import { NativeMessagingStub } from './chromeNative.js';
import { StorageAreaStub } from './chromeStorage.js';
import { TabsStub } from './chromeTabs.js';
import { BackgroundBrowserStub } from './chromeWindows.js';
import { FirefoxBookmarksStub } from './firefoxBookmarks.js';

// --- Types ---

export interface FakeFirefox {
  readonly api: FirefoxBrowser;
  readonly bookmarks: FirefoxBookmarksStub;
  readonly history: HistoryApiStub;
  readonly tabs: TabsStub;
  readonly windows: BackgroundBrowserStub;
  readonly storage: StorageAreaStub;
  /** browser.storage.session: cleared with the browser session, as its session rules are. */
  readonly session: StorageAreaStub;
  readonly native: NativeMessagingStub;
  /** Every tab navigation and opening, in order: `update <url>`, `create <url> active=<b>`. */
  readonly opened: string[];
  /** Every sidebar call, in order: `open`. */
  readonly sidebar: string[];
}

// --- Constants ---

/** Background-tab windows hold tab ids from 101 up; open tabs from 1 up. */
const FIRST_BACKGROUND_TAB = 100;

// --- Builder ---

/** A fresh Firefox profile's `browser` namespace. `sidebarRefuses`: sidebarAction.open rejects (not a user action). */
export function fakeFirefox(options: { readonly sidebarRefuses?: boolean } = {}): FakeFirefox {
  const bookmarks = new FirefoxBookmarksStub();
  const history = new HistoryApiStub();
  const tabs = new TabsStub();
  const windows = new BackgroundBrowserStub();
  const storage = new StorageAreaStub();
  const session = new StorageAreaStub();
  const native = new NativeMessagingStub({ firefox: true });
  const opened: string[] = [];
  const sidebar: string[] = [];
  const events = {
    onCreated: new EventStub<[string, never]>(),
    onMoved: new EventStub<[string, { parentId: string; oldParentId: string }]>(),
    onChanged: new EventStub<[string, unknown]>(),
    onRemoved: new EventStub<[string, { parentId: string }]>(),
  };
  const api: FirefoxBrowser = {
    bookmarks: Object.assign(bookmarks, events),
    history,
    tabs: {
      query: () => tabs.query(),
      get: (tabId) => windows.tabs.get(tabId),
      remove: (tabId) => windows.tabs.remove(tabId),
      update: (tabOrProperties: number | { url: string }, properties?: { url: string }) =>
        typeof tabOrProperties === 'number'
          ? windows.tabs.update(tabOrProperties, properties ?? { url: '' })
          : Promise.resolve(void opened.push(`update ${tabOrProperties.url}`)),
      create: (p) => Promise.resolve(void opened.push(`create ${p.url} active=${String(p.active)}`)),
    },
    scripting: {
      executeScript: (injection) =>
        injection.target.tabId > FIRST_BACKGROUND_TAB ? windows.scripting.executeScript(injection) : tabs.executeScript(injection),
    },
    windows: {
      create: (data: { url: string; focused: boolean; state?: string; type?: string }) => {
        if (data.type === 'popup') return Promise.resolve(void opened.push(`popup ${data.url} focused=${String(data.focused)}`));
        return windows.windows.create({ url: data.url, focused: data.focused, state: data.state ?? 'normal' });
      },
      get: (id, populate) => windows.windows.get(id, populate),
      remove: (id) => windows.windows.remove(id),
    },
    storage: { local: storage, session },
    declarativeNetRequest: windows.declarativeNetRequest,
    runtime: Object.assign(native, {
      id: 'dynomark@tds.dynomark',
      getURL: (path: string) => `moz-extension://self/${path}`,
      onMessage: new EventStub<[unknown, { id?: string }, (response: unknown) => void], boolean>(),
    }),
    sidebarAction: {
      open: () => {
        sidebar.push('open');
        return options.sidebarRefuses === true
          ? Promise.reject(new Error('sidebarAction.open may only be called from a user input handler'))
          : Promise.resolve();
      },
    },
    omnibox: {
      onInputChanged: new EventStub(),
      onInputEntered: new EventStub(),
      setDefaultSuggestion: () => undefined,
    },
    commands: { onCommand: new EventStub<[string]>() },
  };
  return { api, bookmarks, history, tabs, windows, storage, session, native, opened, sidebar };
}
