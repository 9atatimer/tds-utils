// indexCache.test.ts -- the LocalIndex and its Frecency held in memory for
// tier-1 search (design, Goal 4; glossary "Frecency"). Every stored index
// replaces the rows at once and its frecency once built; the frecency search
// ranks by is always that of the rows it searches.

import { describe, expect, it } from 'vitest';
import { IndexCache } from '../../../src/app/indexCache.js';
import type { LocalIndexRow, Visit } from '../../../src/domain/search.js';
import type { Url } from '../../../src/domain/values.js';
import type { HistoryPort } from '../../../src/ports/history.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeHistory } from '../../fakes/FakeHistory.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';

// --- Builders ---

const NOW = 1_790_000_000_000;
const DAY = 86_400_000;

function row(identity: string): LocalIndexRow {
  return { identity, title: identity, path: { root: 'bar', names: ['Dynomark'] }, tags: [], summary: '' };
}

/** A FakeHistory whose lookups made while held wait until release(); lookups made after pass() go straight through. */
class HeldHistory implements HistoryPort {
  private held = false;
  private readonly waiting: (() => void)[] = [];

  constructor(private readonly inner: FakeHistory) {}

  hold(): void {
    this.held = true;
  }

  pass(): void {
    this.held = false;
  }

  release(): void {
    this.waiting.splice(0).forEach((go) => go());
  }

  async visitsTo(url: Url): Promise<readonly Visit[]> {
    if (this.held) await new Promise<void>((go) => this.waiting.push(go));
    return this.inner.visitsTo(url);
  }
}

// --- Tests ---

describe('The in-memory index and its frecency -- IndexCache', () => {
  it('Given two stored indexes whose older frecency build finishes last, When both builds finish, Then the frecency is of the newer index', async () => {
    const visits = new FakeHistory();
    visits.recordVisit('https://a.example/', NOW - DAY);
    visits.recordVisit('https://b.example/', NOW - DAY);
    const history = new HeldHistory(visits);
    const work: Promise<unknown>[] = [];
    const cache = new IndexCache({ storage: new FakeStorage(), history, clock: new FakeClock(NOW) }, (w) => work.push(w));
    const storage = cache.observing(new FakeStorage());

    history.hold();
    await storage.saveLocalIndex([row('https://a.example/')]);
    history.pass();
    const older = work.length;
    await storage.saveLocalIndex([row('https://a.example/'), row('https://b.example/')]);
    await Promise.all(work.slice(older));
    history.release();
    await Promise.all(work);

    expect(cache.index().map((r) => r.identity)).toEqual(['https://a.example/', 'https://b.example/']);
    expect(cache.frecency().has('https://b.example/')).toBe(true);
  });
});
