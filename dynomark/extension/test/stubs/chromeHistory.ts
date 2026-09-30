// chromeHistory.ts -- a tiny chrome.history stand-in: visits by exact URL,
// returned in insertion order (the real API promises no order), with
// fractional visit times as Chrome reports them.

import type { HistoryApi } from '../../src/adapters/chrome/history.js';

export class HistoryApiStub implements HistoryApi {
  private readonly visits = new Map<string, number[]>();

  /** Record one visit to `url` at `visitTime` ms. */
  addVisit(url: string, visitTime: number): void {
    this.visits.set(url, [...(this.visits.get(url) ?? []), visitTime]);
  }

  getVisits(details: { url: string }): Promise<{ visitTime?: number }[]> {
    return Promise.resolve((this.visits.get(details.url) ?? []).map((visitTime) => ({ visitTime })));
  }
}
