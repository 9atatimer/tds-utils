/// <reference types="chrome" />
// backgroundTab.ts -- the writer's BackgroundTabPort (design, Future
// Considerations "Background-tab capture (MVP)"; task-031): open a background
// tab of an unfocused, minimized window, navigate it to the saved URL, wait
// for it to load (up to a timeout), read it as from any tab (readPage, the
// open-tab adapter's extraction, which also reports the URL it read), and
// close the window whatever happened. The writer's browser is usually signed
// in to the same sites, so this recovers logged-in content for saves made on
// a reader device or a phone. One capture runs at a time: a burst of synced
// saves opens one window after another.
//
// A guarded load (the daemon's address policy refuses private addresses;
// issue #534) installs declarativeNetRequest session rules scoped to the
// capture tab before it navigates: every request of that tab -- the main
// frame and each redirect hop included -- to a loopback, private, link-local,
// reserved or multicast IP literal, a single-label host, or a .local,
// .localhost, .internal or .home.arpa name is blocked before it is sent. A
// name that resolves to a private address is not caught here (the extension
// cannot resolve DNS): the use case vets where the load ended with the
// daemon. Rules that cannot be installed fail the load closed. The rules go
// after the window does.
//
// A worker terminated while the page loads never reaches the close, so the
// open window is recorded in extension storage (key `capture_window`) until
// it is closed, and the next worker's sweep() closes it -- only when that id
// still names a minimized window holding the one tab it opened -- and removes
// any rules it left.

import type { Url } from '../../domain/values.js';
import type { BackgroundLoad, BackgroundTabPort, LoadedPage } from '../../ports/backgroundTab.js';
import type { Timer } from '../../ports/timer.js';
import { SystemTimer } from '../timer.js';
import type { StorageAreaApi } from './storage.js';
import { MAX_PAGE_UNITS, isReadPage, readPage, type ScriptingApi } from './tabContent.js';

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
  get(tabId: number): Promise<{ status?: string | undefined; url?: string | undefined }>;
  update(tabId: number, properties: { url: string }): Promise<unknown>;
}

/** A session rule that blocks one tab's requests whose URL matches a pattern. */
export interface BlockRule {
  readonly id: number;
  readonly priority: number;
  readonly action: { readonly type: 'block' };
  readonly condition: {
    readonly regexFilter: string;
    readonly isUrlFilterCaseSensitive: false;
    readonly tabIds: number[];
    /** Only main_frame; absent means every type but main_frame. */
    readonly resourceTypes?: ['main_frame'];
  };
}

/** The part of chrome.declarativeNetRequest (and Firefox's browser.declarativeNetRequest) this adapter uses. */
export interface SessionRulesApi {
  updateSessionRules(options: { removeRuleIds?: number[]; addRules?: BlockRule[] }): Promise<void>;
}

// --- Constants ---

/** How long a background page may take to load before it is given up (the daemon then fetches). */
export const BACKGROUND_LOAD_TIMEOUT_MS = 20_000;
/** How often the tab's load status is checked. */
const POLL_MS = 250;
/** The storage key of the window a capture has open. */
const OPEN_WINDOW_KEY = 'capture_window';
/** The page the capture window opens on, before its rules are in place. */
const BLANK = 'about:blank';

/** A URL up to its host: scheme, then any userinfo. */
const HOST_START = '^[a-z][a-z0-9+.-]*://(?:[^/?#@]*@)?';
/** A URL after its host: an optional trailing dot, an optional port, then the path, query, fragment or the end. */
const HOST_END = '\\.?(?::[0-9]*)?(?:[/?#]|$)';
/**
 * The private hosts a guarded load never reaches, by literal, as browser-canonical URLs spell them. One
 * regexFilter per entry: Chromium refuses a regex rule over its compiled-size limit (memoryLimitExceeded),
 * which the whole IPv4 set in one pattern is, so it is two.
 */
const PRIVATE_HOSTS: readonly string[] = [
  // IPv4: this network, private, loopback and link-local.
  '(?:0|10|127)\\.[0-9.]+|169\\.254\\.[0-9.]+|192\\.168\\.[0-9.]+|172\\.(?:1[6-9]|2[0-9]|3[01])\\.[0-9.]+',
  // IPv4: shared, IETF and documentation ranges, benchmarking, multicast and reserved.
  '100\\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\\.[0-9.]+|192\\.0\\.[02]\\.[0-9]+|198\\.1[89]\\.[0-9.]+' +
    '|198\\.51\\.100\\.[0-9]+|203\\.0\\.113\\.[0-9]+|(?:22[4-9]|2[3-5][0-9])\\.[0-9.]+',
  // IPv6: every literal. The daemon's policy refuses many ranges (6to4, Teredo, NAT64, discard,
  // special use), and a public IPv6 literal is rare in a bookmark; the daemon's fetch still captures it.
  '\\[[^\\]]*\\]',
  // Names: a single label (localhost, intranet), and the names that are local by definition.
  '[^./?#@:\\[\\]]+|(?:[^/?#@:\\[\\]]*\\.)?(?:local|localhost|internal|home\\.arpa)',
];
/** Session rule ids this adapter owns: one main_frame and one every-other-type rule per pattern. */
const RULE_ID_BASE = 53_400;
const RULE_IDS: number[] = PRIVATE_HOSTS.flatMap((_, k) => [ruleId(k, 'main_frame'), ruleId(k, 'other')]);

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

// --- Pure helpers ---

/** The session rule id of pattern `k`'s main_frame rule, or of its rule for every other request type. */
function ruleId(k: number, types: 'main_frame' | 'other'): number {
  return RULE_ID_BASE + 2 * k + (types === 'main_frame' ? 0 : 1);
}

/** The rules that block every request of `tabId` to a private host. */
function blockRules(tabId: number): BlockRule[] {
  return PRIVATE_HOSTS.flatMap((hosts, k): BlockRule[] => {
    const regexFilter = `${HOST_START}(?:${hosts})${HOST_END}`;
    const action = { type: 'block' } as const;
    return [
      {
        id: ruleId(k, 'main_frame'),
        priority: 1,
        action,
        condition: { regexFilter, isUrlFilterCaseSensitive: false, tabIds: [tabId], resourceTypes: ['main_frame'] },
      },
      { id: ruleId(k, 'other'), priority: 1, action, condition: { regexFilter, isUrlFilterCaseSensitive: false, tabIds: [tabId] } },
    ];
  });
}

/** chrome.declarativeNetRequest as a SessionRulesApi: its enums are these strings. */
function chromeSessionRules(): SessionRulesApi {
  return {
    updateSessionRules: (options) =>
      chrome.declarativeNetRequest.updateSessionRules(options as unknown as chrome.declarativeNetRequest.UpdateRuleOptions),
  };
}

// --- The adapter ---

export class ChromeBackgroundTab implements BackgroundTabPort {
  private tail: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly windows: BackgroundWindowsApi = chrome.windows,
    private readonly tabs: BackgroundTabsApi = chrome.tabs,
    private readonly scripting: ScriptingApi = chrome.scripting,
    private readonly timer: Timer = new SystemTimer(),
    private readonly store: StorageAreaApi = chrome.storage.local,
    private readonly rules: SessionRulesApi = chromeSessionRules(),
  ) {}

  /** Load `url` in a background tab, guarded as `load` says, and read it; undefined when it does not load in time, is blocked or cannot be read. Never throws. */
  readTab(url: Url, load: BackgroundLoad): Promise<LoadedPage | undefined> {
    const run = this.tail.then(() => this.capture(url, load));
    this.tail = run;
    return run;
  }

  /** Close the window an earlier worker's capture left open, if it is still that window, and drop its rules. Never throws; captures wait for it. */
  sweep(): Promise<void> {
    const run = this.tail.then(async () => {
      await this.closeLeftOpen();
    });
    this.tail = run;
    return run;
  }

  private async capture(url: Url, load: BackgroundLoad): Promise<LoadedPage | undefined> {
    let windowId: number | undefined;
    let tabId: number | undefined;
    let guarded = false;
    try {
      // An earlier window that will not close keeps the rules (their ids are fixed): no capture until it is gone.
      if (!(await this.closeLeftOpen())) return undefined;
      const opened = await this.windows.create({ url: BLANK, focused: false, state: 'minimized' });
      windowId = opened?.id;
      tabId = opened?.tabs?.[0]?.id;
      if (windowId !== undefined && tabId !== undefined) await this.remember({ window_id: windowId, tab_id: tabId });
      if (tabId === undefined) return undefined;
      if (load.blockPrivateHosts) {
        guarded = true;
        await this.rules.updateSessionRules({ removeRuleIds: RULE_IDS, addRules: blockRules(tabId) });
      }
      await this.tabs.update(tabId, { url });
      if (!(await this.loaded(tabId))) return undefined;
      const [frame] = await this.scripting.executeScript({ target: { tabId }, func: readPage, args: [MAX_PAGE_UNITS] });
      const page = frame?.result;
      return isReadPage(page) && page.text.trim() !== '' ? { title: page.title, text: page.text, url: page.url } : undefined;
    } catch {
      return undefined;
    } finally {
      if (windowId !== undefined) await this.close(windowId);
      // A window that would not close keeps its rules: the next sweep closes it, then removes them.
      if (guarded && tabId !== undefined && (await this.tabGone(tabId))) await this.unblock();
    }
  }

  /**
   * The rules go only once the recorded tab is gone: its page may still be
   * loading, or redirecting, until then. A window not ours is left open and
   * forgotten; its tab keeps the rules until it is gone or the next sweep or capture.
   * True when no window of a capture is left open.
   */
  private async closeLeftOpen(): Promise<boolean> {
    try {
      const left = (await this.store.get(OPEN_WINDOW_KEY))[OPEN_WINDOW_KEY];
      if (isOpenWindow(left)) {
        const win = await this.windows.get(left.window_id, { populate: true }).catch(() => undefined);
        const tabs = win?.tabs ?? [];
        const ours = win?.state === 'minimized' && tabs.length === 1 && tabs[0]?.id === left.tab_id;
        if (ours) await this.close(left.window_id);
        else await this.store.remove(OPEN_WINDOW_KEY);
        if (!(await this.tabGone(left.tab_id))) return !ours;
      }
      await this.unblock();
      return true;
    } catch {
      return false;
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

  /** True when the browser no longer has tab `tabId`. */
  private tabGone(tabId: number): Promise<boolean> {
    return this.tabs.get(tabId).then(
      () => false,
      () => true,
    );
  }

  /** Remove this adapter's block rules (scoped to a tab that is gone, they would block nothing; they are removed anyway). */
  private async unblock(): Promise<void> {
    try {
      await this.rules.updateSessionRules({ removeRuleIds: RULE_IDS });
    } catch {
      return;
    }
  }

  /** True once the tab has left the blank page and reports its load complete; false at the timeout. */
  private async loaded(tabId: number): Promise<boolean> {
    for (let waited = 0; ; waited += POLL_MS) {
      const tab = await this.tabs.get(tabId);
      if (tab.status === 'complete' && tab.url !== BLANK) return true;
      if (waited >= BACKGROUND_LOAD_TIMEOUT_MS) return false;
      await new Promise<void>((resolve) => this.timer.after(POLL_MS, resolve));
    }
  }
}
