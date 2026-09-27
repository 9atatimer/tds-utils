// FakeHistory.ts -- an in-memory HistoryPort keyed by exact URL.

import type { Visit } from '../../src/domain/search.js';
import type { EpochMs, Url } from '../../src/domain/values.js';
import type { HistoryPort } from '../../src/ports/history.js';

export class FakeHistory implements HistoryPort {
  private readonly visits = new Map<Url, EpochMs[]>();

  /** Seed one visit, as the browser records a navigation. */
  recordVisit(url: Url, at: EpochMs): void {
    this.visits.set(url, [...(this.visits.get(url) ?? []), at]);
  }

  visitsTo(url: Url): Promise<readonly Visit[]> {
    const times = [...(this.visits.get(url) ?? [])].sort((a, b) => a - b);
    return Promise.resolve(times.map((visited_at) => ({ visited_at })));
  }
}
