// buildFrecency.test.ts -- design glossary "Frecency": a map identity ->
// visit boost derived from browser history through HistoryPort. Contract v1,
// "Identity": the extension asks HistoryPort for the visits of each identity
// it holds, never by normalizing history URLs. Tier-1 search orders within a
// tier by it.

import { describe, expect, it } from 'vitest';
import { buildFrecency } from '../../../src/app/buildFrecency.js';
import type { LocalIndexRow } from '../../../src/domain/search.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeHistory } from '../../fakes/FakeHistory.js';

// --- Builders ---

const NOW = 1_790_000_000_000;
const DAY = 86_400_000;

function row(identity: string): LocalIndexRow {
  return { identity, title: identity, path: { root: 'bar', names: ['Dynomark'] }, tags: [], summary: '' };
}

// --- Tests ---

describe('Frecency is derived from history -- buildFrecency(index, { history, clock })', () => {
  it('Given one visit yesterday and one visit a year ago, When built, Then the recent visit weighs more', async () => {
    const history = new FakeHistory();
    history.recordVisit('https://recent.example/', NOW - DAY);
    history.recordVisit('https://old.example/', NOW - 365 * DAY);
    const frecency = await buildFrecency([row('https://recent.example/'), row('https://old.example/')], {
      history,
      clock: new FakeClock(NOW),
    });
    expect(frecency.get('https://recent.example/') ?? 0).toBeGreaterThan(frecency.get('https://old.example/') ?? 0);
    expect(frecency.get('https://old.example/') ?? 0).toBeGreaterThan(0);
  });

  it('Given the same age, When one identity has more visits, Then it weighs more', async () => {
    const history = new FakeHistory();
    for (const at of [NOW - DAY, NOW - 2 * DAY, NOW - 3 * DAY]) history.recordVisit('https://often.example/', at);
    history.recordVisit('https://once.example/', NOW - DAY);
    const frecency = await buildFrecency([row('https://often.example/'), row('https://once.example/')], {
      history,
      clock: new FakeClock(NOW),
    });
    expect(frecency.get('https://often.example/') ?? 0).toBeGreaterThan(frecency.get('https://once.example/') ?? 0);
  });

  it('Given visits only to a URL variant of an identity, When built, Then the identity gets no boost (history is asked by identity, never normalized)', async () => {
    const history = new FakeHistory();
    history.recordVisit('https://tokio.rs/tokio/tutorial?utm_source=x', NOW - DAY);
    const frecency = await buildFrecency([row('https://tokio.rs/tokio/tutorial')], { history, clock: new FakeClock(NOW) });
    expect(frecency.get('https://tokio.rs/tokio/tutorial') ?? 0).toBe(0);
  });

  it('Given an index, When built, Then the map has no identity the index does not hold', async () => {
    const history = new FakeHistory();
    history.recordVisit('https://elsewhere.example/', NOW - DAY);
    const frecency = await buildFrecency([row('https://a.example/')], { history, clock: new FakeClock(NOW) });
    expect([...frecency.keys()].filter((k) => k !== 'https://a.example/')).toEqual([]);
  });
});
