// runtime.omnibox.test.ts -- the omnibox keyword `bm` (design, "The
// extension": Tier-1 search, Tier-2 search; Goal 4). Every keystroke is
// answered from the LocalIndex at once; when tier 1 is under the named
// thresholds, tier-2 hits are appended after a debounce (a newer keystroke
// cancels the older request's suggestions); Enter navigates to the hit's
// identity. The omnibox itself cannot be typed into in a headless browser,
// so the handler is exercised here and through the background's handle in
// e2e.

import { describe, expect, it } from 'vitest';
import { TIER2_DEBOUNCE_MS } from '../../../src/app/omnibox.js';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { Hit, LocalIndexRow } from '../../../src/domain/search.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { scriptDaemon, sentOf, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

const ROWS: LocalIndexRow[] = [
  {
    identity: 'https://tokio.rs/tokio/tutorial',
    title: 'Tokio tutorial',
    path: { root: 'bar', names: ['Dynomark', 'Rust'] },
    tags: ['rust'],
    summary: 'Async Rust.',
  },
  {
    identity: 'https://serde.rs/',
    title: 'Serde',
    path: { root: 'bar', names: ['Dynomark', 'Rust'] },
    tags: ['rust'],
    summary: 'Serialization.',
  },
];

const CORPUS_HIT = {
  identity: 'https://without.boats/blog/pin/',
  title: 'Pin',
  path: { root: 'bar' as const, names: ['Dynomark', 'Rust'] },
  score: 0.4,
  tier: 'corpus' as const,
};

function answers(r: RequestMessage): ResponseMessage | undefined {
  if (r.type === 'index.pull') return { v: 1, type: 'index.pull.result', re: r.id, rows: ROWS, next_cursor: null };
  if (r.type === 'search') return { v: 1, type: 'search.result', re: r.id, hits: [CORPUS_HIT], next_cursor: null };
  return undefined;
}

async function setup(): Promise<{ w: FakeExtensionWorld; runtime: ExtensionRuntime }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w, {}, answers);
  return { w, runtime: await startRuntime(w) };
}

function type(runtime: ExtensionRuntime, text: string): Hit[][] {
  const rounds: Hit[][] = [];
  runtime.omniboxInput(text, (hits) => rounds.push([...hits]));
  return rounds;
}

// --- Tests ---

describe('Omnibox bm -- tier 1 per keystroke, tier 2 after the debounce', () => {
  it('Given the pulled index, When "tokio" is typed, Then tier-1 suggestions come at once with no transport call', async () => {
    const { w, runtime } = await setup();
    const before = w.connection().sent.length;
    const rounds = type(runtime, 'tokio');
    expect(rounds).toHaveLength(1);
    expect(rounds[0]?.map((h) => [h.identity, h.tier])).toEqual([['https://tokio.rs/tokio/tutorial', 'local']]);
    expect(w.connection().sent).toHaveLength(before);
  });

  it('Given tier 1 is under the thresholds, When the debounce passes, Then search is sent and corpus hits are appended below tier 1', async () => {
    const { w, runtime } = await setup();
    const rounds = type(runtime, 'tokio');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    await runtime.idle();
    expect(sentOf(w, 'search').map((r) => r.query)).toEqual(['tokio']);
    expect(rounds.at(-1)?.map((h) => h.tier)).toEqual(['local', 'corpus']);
  });

  it('Given a second keystroke inside the debounce, When time passes, Then only the latest query reaches the daemon', async () => {
    const { w, runtime } = await setup();
    const first = type(runtime, 'tok');
    await w.timer().advance(TIER2_DEBOUNCE_MS - 1);
    type(runtime, 'tokio');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    await runtime.idle();
    expect(sentOf(w, 'search').map((r) => r.query)).toEqual(['tokio']);
    expect(first).toHaveLength(1);
  });

  it('Given the daemon is unreachable, When tier 2 is due, Then the tier-1 suggestions stand', async () => {
    const { w, runtime } = await setup();
    w.connection().unreachable(true);
    const rounds = type(runtime, 'tokio');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    await runtime.idle();
    expect(rounds).toHaveLength(1);
  });

  it('Given a blank query, When typed, Then there are no suggestions and nothing is sent', async () => {
    const { w, runtime } = await setup();
    const rounds = type(runtime, '   ');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    expect(rounds).toEqual([[]]);
    expect(sentOf(w, 'search')).toEqual([]);
  });
});

describe('Omnibox bm -- Enter navigates to the hit identity', () => {
  it('Given a suggestion was picked (its content is the identity), When entered, Then that identity opens in the disposition asked for', async () => {
    const { w, runtime } = await setup();
    type(runtime, 'serde');
    await runtime.omniboxEnter('https://serde.rs/', 'currentTab');
    expect(w.navigator.opened).toEqual([{ url: 'https://serde.rs/', disposition: 'currentTab' }]);
  });

  it('Given plain text with a tier-1 hit, When entered, Then the best hit opens', async () => {
    const { w, runtime } = await setup();
    await runtime.omniboxEnter('tokio', 'newForegroundTab');
    expect(w.navigator.opened).toEqual([{ url: 'https://tokio.rs/tokio/tutorial', disposition: 'newForegroundTab' }]);
  });

  it('Given text matching nothing, When entered, Then nothing opens', async () => {
    const { w, runtime } = await setup();
    await runtime.omniboxEnter('zzzz', 'currentTab');
    expect(w.navigator.opened).toEqual([]);
  });

  it('Given a corpus hit whose identity is not http(s), When entered, Then it is not opened', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, {}, (r) =>
      r.type === 'search'
        ? { v: 1, type: 'search.result', re: r.id, hits: [{ ...CORPUS_HIT, identity: 'javascript:alert(1)' }], next_cursor: null }
        : answers(r),
    );
    const runtime = await startRuntime(w);
    type(runtime, 'pin');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    await runtime.idle();
    await runtime.omniboxEnter('javascript:alert(1)', 'currentTab');
    expect(w.navigator.opened).toEqual([]);
  });
});
