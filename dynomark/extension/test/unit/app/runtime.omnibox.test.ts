// runtime.omnibox.test.ts -- the omnibox keyword `bm` (design, "The
// extension": Tier-1 search, Tier-2 search; Goal 4). Every keystroke is
// answered from the LocalIndex at once; when tier 1 is under the named
// thresholds, tier-2 hits are appended after a debounce (a newer keystroke
// cancels the older request's suggestions); Enter navigates to the hit's
// identity. The last row is always `Ask: <query>` (design, "Ask
// fall-through"): entering it, or entering with no hit, opens the chat
// surface with the query pre-sent. The omnibox itself cannot be typed into in
// a headless browser, so the handler is exercised here and through the
// background's handle in e2e.

import { describe, expect, it } from 'vitest';
import { TIER2_DEBOUNCE_MS } from '../../../src/app/omnibox.js';
import { ExtensionRuntime } from '../../../src/app/runtime.js';
import { askRowContent, type OmniboxRows } from '../../../src/domain/omnibox.js';
import type { LocalIndexRow } from '../../../src/domain/search.js';
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

function type(runtime: ExtensionRuntime, text: string): OmniboxRows[] {
  const rounds: OmniboxRows[] = [];
  runtime.omniboxInput(text, (rows) => rounds.push(rows));
  return rounds;
}

// --- Tests ---

describe('Omnibox bm -- tier 1 per keystroke, tier 2 after the debounce', () => {
  it('Given the pulled index, When "tokio" is typed, Then tier-1 suggestions come at once with no transport call', async () => {
    const { w, runtime } = await setup();
    const before = w.connection().sent.length;
    const rounds = type(runtime, 'tokio');
    expect(rounds).toHaveLength(1);
    expect(rounds[0]?.hits.map((h) => [h.identity, h.tier])).toEqual([['https://tokio.rs/tokio/tutorial', 'local']]);
    expect(w.connection().sent).toHaveLength(before);
  });

  it('Given tier 1 is under the thresholds, When the debounce passes, Then search is sent and corpus hits are appended below tier 1', async () => {
    const { w, runtime } = await setup();
    const rounds = type(runtime, 'tokio');
    await w.timer().advance(TIER2_DEBOUNCE_MS);
    await runtime.idle();
    expect(sentOf(w, 'search').map((r) => r.query)).toEqual(['tokio']);
    expect(rounds.at(-1)?.hits.map((h) => h.tier)).toEqual(['local', 'corpus']);
    expect(rounds.at(-1)?.ask).toBe('tokio');
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
    expect(rounds).toEqual([{ hits: [], enter_asks: false }]);
    expect(sentOf(w, 'search')).toEqual([]);
  });
});

describe('Omnibox bm -- the Ask row', () => {
  it('Given hits, When typed, Then the Ask row follows them and Enter on the text does not ask', async () => {
    const { runtime } = await setup();
    const [first] = type(runtime, 'tokio');
    expect(first).toMatchObject({ ask: 'tokio', enter_asks: false });
  });

  it('Given no hit, When typed, Then the Ask row is the only row and the default', async () => {
    const { runtime } = await setup();
    expect(type(runtime, 'zzzz')[0]).toEqual({ hits: [], ask: 'zzzz', enter_asks: true });
  });

  it('Given the Ask row, When it is entered, Then the chat surface opens with the query pre-sent and nothing is navigated', async () => {
    const { w, runtime } = await setup();
    type(runtime, 'tokio');
    await runtime.omniboxEnter(askRowContent('tokio'), 'currentTab');
    expect(w.surface.opened).toEqual(['tokio']);
    expect(w.navigator.opened).toEqual([]);
  });

  it('Given the keyboard command, When it fires, Then the chat surface opens empty', async () => {
    const { w, runtime } = await setup();
    await runtime.openChat();
    expect(w.surface.opened).toEqual([undefined]);
  });
});

describe('Omnibox bm -- a pulled index that cannot be stored is still searched', () => {
  it('Given the browser refuses to store the pulled index (quota), When a keystroke arrives, Then tier 1 searches the pulled rows and the refusal is reported', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, {}, answers);
    w.storage.saveLocalIndex = () => Promise.reject(new Error('Resource::kQuotaBytes quota exceeded'));
    const runtime = await startRuntime(w);

    const rounds = type(runtime, 'tokio');

    expect(rounds[0]?.hits.map((h) => h.identity)).toEqual(['https://tokio.rs/tokio/tutorial']);
    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain('quota exceeded');
  });
});

describe('Omnibox bm -- Enter navigates to the hit identity', () => {
  it('Given a suggestion was picked (its content is the identity), When entered, Then that identity opens in the disposition asked for', async () => {
    const { w, runtime } = await setup();
    type(runtime, 'serde');
    await runtime.omniboxEnter('https://serde.rs/', 'currentTab');
    expect(w.navigator.opened).toEqual([{ url: 'https://serde.rs/', disposition: 'currentTab' }]);
  });

  it('Given the worker restarted between the keystrokes and Enter, When the picked hit comes back, Then it still opens (a picked row hands back its identity)', async () => {
    const { w, runtime } = await setup();
    type(runtime, 'serde');
    w.restart();
    scriptDaemon(w, {}, answers);
    const fresh = new ExtensionRuntime(w.worker());
    void fresh.start();
    await fresh.omniboxEnter('https://serde.rs/', 'currentTab');
    expect(w.navigator.opened).toEqual([{ url: 'https://serde.rs/', disposition: 'currentTab' }]);
    expect(w.surface.opened).toEqual([]);
  });

  it('Given a tier-2 hit was picked on a worker that is gone, When entered on a fresh one, Then its identity opens rather than being asked as a question', async () => {
    const { w } = await setup();
    w.restart();
    scriptDaemon(w, {}, answers);
    const fresh = await startRuntime(w);
    await fresh.omniboxEnter(CORPUS_HIT.identity, 'currentTab');
    expect(w.navigator.opened).toEqual([{ url: CORPUS_HIT.identity, disposition: 'currentTab' }]);
    expect(w.surface.opened).toEqual([]);
  });

  it('Given plain text with a tier-1 hit, When entered, Then the best hit opens', async () => {
    const { w, runtime } = await setup();
    await runtime.omniboxEnter('tokio', 'newForegroundTab');
    expect(w.navigator.opened).toEqual([{ url: 'https://tokio.rs/tokio/tutorial', disposition: 'newForegroundTab' }]);
  });

  it('Given text matching nothing, When entered, Then no page opens and the chat surface opens with the text pre-sent', async () => {
    const { w, runtime } = await setup();
    await runtime.omniboxEnter('zzzz', 'currentTab');
    expect(w.navigator.opened).toEqual([]);
    expect(w.surface.opened).toEqual(['zzzz']);
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
