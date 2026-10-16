// namespace.ts -- Firefox's `browser` namespace: the promise-based
// WebExtensions APIs the Firefox adapters are built on (task-032), typed as
// exactly the parts they use. No ambient Firefox typings are installed; each
// part is the narrow API interface its adapter already declares, so a stand-in
// in the tests and the real namespace satisfy the same shape.

import type { BackgroundTabsApi, BackgroundWindowsApi } from '../chrome/backgroundTab.js';
import type { ChatTabsApi, ChatWindowsApi, ExtensionUrlApi } from '../chrome/chatSurface.js';
import type { CommandsApi } from '../chrome/commands.js';
import type { HistoryApi } from '../chrome/history.js';
import type { NativeRuntimeApi } from '../chrome/nativeTransport.js';
import type { NavigatorTabsApi } from '../chrome/navigator.js';
import type { OmniboxApi } from '../chrome/omnibox.js';
import type { PageServerApi } from '../chrome/pageChannel.js';
import type { StorageAreaApi } from '../chrome/storage.js';
import type { ScriptingApi, TabsApi } from '../chrome/tabContent.js';
import type { FirefoxBookmarkEventsApi } from './bookmarkEvents.js';
import type { FirefoxBookmarksApi } from './bookmarkTree.js';

// --- Types ---

/** The part of browser.sidebarAction the chat surface uses. */
export interface SidebarActionApi {
  /** Rejects unless called while the browser is handling a user action. */
  open(): Promise<void>;
}

/** The parts of Firefox's `browser` namespace the extension uses. */
export interface FirefoxBrowser {
  readonly bookmarks: FirefoxBookmarksApi & FirefoxBookmarkEventsApi;
  readonly history: HistoryApi;
  readonly tabs: TabsApi & BackgroundTabsApi & ChatTabsApi & NavigatorTabsApi;
  readonly scripting: ScriptingApi;
  readonly windows: BackgroundWindowsApi & ChatWindowsApi;
  readonly storage: { readonly local: StorageAreaApi };
  readonly runtime: NativeRuntimeApi & ExtensionUrlApi & PageServerApi;
  readonly sidebarAction: SidebarActionApi;
  readonly omnibox: OmniboxApi;
  readonly commands: CommandsApi;
}

// --- Entry ---

/** The live `browser` namespace (a Firefox extension context only). */
export function firefoxBrowser(): FirefoxBrowser {
  return (globalThis as unknown as { readonly browser: FirefoxBrowser }).browser;
}
