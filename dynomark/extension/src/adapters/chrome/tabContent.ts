/// <reference types="chrome" />
// tabContent.ts -- the extension-side ContentSourcePort on chrome.tabs and
// chrome.scripting (design, "Capture from the open tab"; Security: needs the
// all-sites host permission). Readable-text extraction happens here, inside
// the adapter (design, Key Decisions, "Extraction"): the page's <article>,
// else its <main>, else its <body>, as rendered text (innerText). A tab that
// cannot be scripted (an error page, a protected page) yields nothing.

import { MAX_CAPTURE_TEXT } from '../../domain/limits.js';
import type { TabContent } from '../../domain/capture.js';
import type { Url } from '../../domain/values.js';
import type { ContentSourcePort } from '../../ports/contentSource.js';

// --- Types ---

/** What the injected reader returns. */
export interface PageText {
  readonly title: string;
  readonly text: string;
}

interface TabLike {
  readonly id?: number | undefined;
  readonly url?: string | undefined;
  readonly lastAccessed?: number | undefined;
}

/** The part of chrome.tabs this adapter uses. */
export interface TabsApi {
  query(queryInfo: Record<string, never>): Promise<readonly TabLike[]>;
}

/** The part of chrome.scripting this adapter uses. */
export interface ScriptingApi {
  executeScript(injection: {
    target: { tabId: number };
    func: (maxUnits: number) => PageText;
    args: [number];
  }): Promise<readonly { result?: unknown }[]>;
}

// --- Constants ---

/** UTF-16 units read from the page: enough for the contract's code-point cap; the domain cuts exactly. */
export const MAX_PAGE_UNITS = MAX_CAPTURE_TEXT * 2;

// --- Injected (runs in the page; must stay self-contained) ---

/** The page title and the rendered text of its article, main or body, cut to `maxUnits` UTF-16 units. */
export function readPage(maxUnits: number): PageText {
  const root: HTMLElement | null = document.querySelector('article') ?? document.querySelector('main') ?? document.body;
  const text = root?.innerText ?? '';
  return { title: document.title, text: text.length > maxUnits ? text.slice(0, maxUnits) : text };
}

// --- Predicates ---

/** True when an injected reader's result has the PageText shape. */
export function isPageText(value: unknown): value is PageText {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v['title'] === 'string' && typeof v['text'] === 'string';
}

// --- The adapter ---

export class ChromeTabContent implements ContentSourcePort {
  constructor(
    private readonly tabs: TabsApi = chrome.tabs,
    private readonly scripting: ScriptingApi = chrome.scripting,
  ) {}

  async readTab(url: Url): Promise<TabContent | undefined> {
    const showing = (await this.tabs.query({}))
      .filter((t): t is TabLike & { id: number } => t.url === url && t.id !== undefined)
      .sort((a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0));
    for (const tab of showing) {
      const page = await this.read(tab.id);
      if (page !== undefined) return { title: page.title, text: page.text };
    }
    return undefined;
  }

  private async read(tabId: number): Promise<PageText | undefined> {
    try {
      const [frame] = await this.scripting.executeScript({ target: { tabId }, func: readPage, args: [MAX_PAGE_UNITS] });
      return isPageText(frame?.result) ? frame.result : undefined;
    } catch {
      return undefined;
    }
  }
}
