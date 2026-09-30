// indexCache.test.ts -- the LocalIndex and its Frecency held in memory for
// tier-1 search (design, Goal 4; glossary "Frecency"). Every stored index
// replaces the rows at once and its frecency once built; the frecency search
// ranks by is always that of the rows it searches.

import { describe, expect, it } from 'vitest';
import { IndexCache } from '../../../src/app/indexCache.js';
import type { LocalIndexRow } from '../../../src/domain/search.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeHistory } from '../../fakes/FakeHistory.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';

// --- Builders ---

const NOW = 1_790_000_000_000;
const DAY = 86_400_000;

function row(identity: string): LocalIndexRow {
  return { identity, title: identity, path: { root: 'bar', names: ['Dynomark'] }, tags: [], summary: '' };
}

// --- Tests ---

describe('The in-memory index and its frecency -- IndexCache', () => {
  it('Given two stored indexes whose older frecency build finishes last, When both builds finish, Then the frecency is of the newer index', async () => {
    const history = new FakeHistory();
    history.recordVisit('https://a.example/', NOW - DAY);
    history.recordVisit('https://b.example/', NOW - DAY);
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
