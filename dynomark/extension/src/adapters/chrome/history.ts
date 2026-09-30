/// <reference types="chrome" />
// history.ts -- the HistoryPort on chrome.history: every visit to exactly one
// URL (getVisits matches the URL as given; the extension never normalizes),
// oldest first, in whole milliseconds.

import type { Visit } from '../../domain/search.js';
import type { Url } from '../../domain/values.js';
import type { HistoryPort } from '../../ports/history.js';

// --- Types ---

/** The part of chrome.history this adapter uses. */
export interface HistoryApi {
  getVisits(details: { url: string }): Promise<readonly { visitTime?: number }[]>;
}

// --- The adapter ---

export class ChromeHistory implements HistoryPort {
  constructor(private readonly api: HistoryApi = chrome.history) {}

  async visitsTo(url: Url): Promise<readonly Visit[]> {
    const items = await this.api.getVisits({ url });
    return items
      .flatMap((item) => (item.visitTime === undefined ? [] : [Math.floor(item.visitTime)]))
      .sort((a, b) => a - b)
      .map((visited_at) => ({ visited_at }));
  }
}
