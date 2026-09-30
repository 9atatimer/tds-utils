// FakeHistory.ts -- an in-memory HistoryPort keyed by exact URL. Lookups
// answer asynchronously, as the browser's do; a test can hold them, make one
// URL's lookups fail, and read how many were ever in flight at once.

import type { Visit } from '../../src/domain/search.js';
import type { EpochMs, Url } from '../../src/domain/values.js';
import type { HistoryPort } from '../../src/ports/history.js';

export class FakeHistory implements HistoryPort {
  /** The most lookups that were ever in flight at once. */
  peak = 0;

  private readonly visits = new Map<Url, EpochMs[]>();
  private readonly refused = new Set<Url>();
  private readonly waiting: (() => void)[] = [];
  private held = false;
  private inFlight = 0;

  /** Seed one visit, as the browser records a navigation. */
  recordVisit(url: Url, at: EpochMs): void {
    this.visits.set(url, [...(this.visits.get(url) ?? []), at]);
  }

  /** Lookups asked from now on wait until release(). */
  hold(): void {
    this.held = true;
  }

  /** Lookups asked from now on answer at once; those already held keep waiting for release(). */
  pass(): void {
    this.held = false;
  }

  /** Answer every held lookup. */
  release(): void {
    this.waiting.splice(0).forEach((go) => go());
  }

  /** Every lookup of `url` fails from now on, as a browser call can. */
  refuse(url: Url): void {
    this.refused.add(url);
  }

  async visitsTo(url: Url): Promise<readonly Visit[]> {
    this.inFlight += 1;
    this.peak = Math.max(this.peak, this.inFlight);
    try {
      if (this.held) await new Promise<void>((go) => this.waiting.push(go));
      else await Promise.resolve();
      if (this.refused.has(url)) throw new Error(`history lookup of ${url} failed`);
      const times = [...(this.visits.get(url) ?? [])].sort((a, b) => a - b);
      return times.map((visited_at) => ({ visited_at }));
    } finally {
      this.inFlight -= 1;
    }
  }
}
