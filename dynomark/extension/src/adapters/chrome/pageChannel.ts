/// <reference types="chrome" />
// pageChannel.ts -- extension pages <-> background over chrome.runtime
// messaging. A page request travels as { dynomark_page: request }; the
// background answers only such messages, only from this extension, and only
// for a known kind. The page side never throws: a background that cannot be
// reached is an ok: false answer.

import type { PageClient, PageRequest, PageResponse } from '../../ports/pages.js';

// --- Types ---

interface Sender {
  readonly id?: string | undefined;
}

/** The part of chrome.runtime the background side uses. */
export interface PageServerApi {
  readonly id: string;
  readonly onMessage: {
    addListener(callback: (message: unknown, sender: Sender, sendResponse: (response: unknown) => void) => boolean): void;
  };
}

/** The part of chrome.runtime a page uses. */
export interface PageClientApi {
  readonly id: string;
  sendMessage(message: unknown): Promise<unknown>;
}

// --- Constants ---

const ENVELOPE = 'dynomark_page';
const KINDS: ReadonlySet<string> = new Set([
  'overview',
  'settings.set',
  'batch.list',
  'undo',
  'job.list',
  'job.retry',
  'ask',
  'explain',
  'open',
  'file',
  'diff.list',
  'diff.page',
  'diff.propose',
  'diff.accept',
  'outline',
  'folder.flags',
  'backfill.start',
]);

// --- Predicates ---

function pageRequestOf(message: unknown): PageRequest | undefined {
  if (typeof message !== 'object' || message === null || !(ENVELOPE in message)) return undefined;
  const request = (message as Record<string, unknown>)[ENVELOPE];
  if (typeof request !== 'object' || request === null) return undefined;
  const kind = (request as Record<string, unknown>)['kind'];
  return typeof kind === 'string' && KINDS.has(kind) ? (request as PageRequest) : undefined;
}

function isPageResponse(value: unknown): value is PageResponse {
  return typeof value === 'object' && value !== null && typeof (value as Record<string, unknown>)['ok'] === 'boolean';
}

// --- Entry: the background side ---

/** Answer every page request from this extension with `answer`. */
export function servePages(answer: (request: PageRequest) => Promise<PageResponse>, api: PageServerApi = chrome.runtime): void {
  api.onMessage.addListener((message, sender, sendResponse) => {
    const request = sender.id === api.id ? pageRequestOf(message) : undefined;
    if (request === undefined) return false;
    void answer(request).then(sendResponse, (error: unknown) => sendResponse({ ok: false, error: String(error) }));
    return true;
  });
}

// --- The page side ---

export class ChromePageClient implements PageClient {
  constructor(private readonly api: PageClientApi = chrome.runtime) {}

  async request(request: PageRequest): Promise<PageResponse> {
    try {
      const response = await this.api.sendMessage({ [ENVELOPE]: request });
      return isPageResponse(response) ? response : { ok: false, error: 'the background gave no answer' };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  }
}
