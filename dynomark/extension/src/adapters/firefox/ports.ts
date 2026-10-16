// ports.ts -- every adapter the background runtime needs, on Firefox's
// `browser` namespace (task-032; the Firefox entry point's one call into this
// layer). The bookmark tree is Firefox's own dialect; everything else is the
// shared WebExtensions adapter, given browser.* where Chrome's is given
// chrome.*, because the two APIs agree there: history (getVisits by exact
// URL), tab content (tabs.query + scripting.executeScript), the background
// tab (windows.create minimized and unfocused, its private-host block rules
// on declarativeNetRequest session rules, its open tab in storage.session), storage.local, native
// messaging (a lost host reported on port.error), and tab navigation. The
// chat surface is the sidebar, falling back to Chrome's popup window. A
// background window an earlier background script left open is closed.

import { SystemClock } from '../clock.js';
import { CryptoIdSource } from '../idSource.js';
import { SystemTimer } from '../timer.js';
import { ChromeBackgroundTab } from '../chrome/backgroundTab.js';
import { ChromeChatSurface } from '../chrome/chatSurface.js';
import { ChromeHistory } from '../chrome/history.js';
import { NativeMessagingTransport } from '../chrome/nativeTransport.js';
import { ChromeNavigator } from '../chrome/navigator.js';
import { ChromeStorage } from '../chrome/storage.js';
import { ChromeTabContent } from '../chrome/tabContent.js';
import { FirefoxBookmarkTree } from './bookmarkTree.js';
import { FirefoxChatSurface } from './chatSurface.js';
import type { FirefoxBrowser } from './namespace.js';

// --- Entry ---

/** The Firefox adapters, one per port, on `api` (the live `browser` namespace in the extension). */
export function firefoxPorts(api: FirefoxBrowser) {
  const timer = new SystemTimer();
  const background = new ChromeBackgroundTab(api.windows, api.tabs, api.scripting, timer, api.storage.session, api.declarativeNetRequest);
  void background.sweep();
  return {
    tree: new FirefoxBookmarkTree(api.bookmarks),
    history: new ChromeHistory(api.history),
    content: new ChromeTabContent(api.tabs, api.scripting),
    background,
    storage: new ChromeStorage(api.storage.local),
    transport: new NativeMessagingTransport(api.runtime),
    clock: new SystemClock(),
    ids: new CryptoIdSource(),
    timer,
    navigator: new ChromeNavigator(api.tabs),
    surface: new FirefoxChatSurface(api.sidebarAction, new ChromeChatSurface(api.windows, api.tabs, api.runtime)),
  };
}
