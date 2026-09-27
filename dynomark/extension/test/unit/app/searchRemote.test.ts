// searchRemote.test.ts -- design Behaviors row "Tier-2 search is requested":
// search_remote(query, *, transport) -> list[Hit]. Tier 2 is asked only when
// tier 1 returned fewer than tier2_min_hits hits or its best score is under
// tier2_min_score (named parameters, values in code); its hits carry tier
// corpus and append below tier 1 (design, "The extension").

import { describe, expect, it } from 'vitest';
import { DaemonError } from '../../../src/app/errors.js';
import { searchRemote } from '../../../src/app/searchRemote.js';
import { TIER2_THRESHOLDS, appendTier2, shouldRequestTier2 } from '../../../src/domain/search.js';
import type { Hit } from '../../../src/domain/search.js';
import { SearchSchema, type RequestMessage, type ResponseMessage } from '../../../src/wire/messages.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';

// --- Builders ---

function hit(identity: string, score: number, tier: Hit['tier']): Hit {
  return { identity, title: identity, path: { root: 'bar', names: ['Dynomark'] }, score, tier };
}

const CORPUS_HITS = [hit('https://only-in-text.example/', 0.61, 'corpus'), hit('https://local.example/', 0.4, 'corpus')];

function corpusDaemon(r: RequestMessage): ResponseMessage {
  if (r.type !== 'search') throw new Error(`unexpected ${r.type}`);
  return { v: 1, type: 'search.result', re: r.id, hits: CORPUS_HITS.map((h) => ({ ...h, tier: 'corpus' as const })), next_cursor: null };
}

// --- Tests ---

describe('Behavior: Tier-2 search is requested -- searchRemote(query, { transport, ids })', () => {
  it('Given tier-1 returned under tier2_min_hits, When requested, Then the daemon is asked and its hits have tier corpus, appended below tier-1', async () => {
    const local = [hit('https://local.example/', 0.9, 'local')];
    expect(local.length).toBeLessThan(TIER2_THRESHOLDS.tier2_min_hits);
    expect(shouldRequestTier2(local)).toBe(true);
    const transport = new FakeTransport();
    transport.autoAnswer(corpusDaemon);
    const corpus = await searchRemote('tokio runtime', { transport, ids: new SequentialIdSource() });
    expect(corpus.map((h) => h.tier)).toEqual(['corpus', 'corpus']);
    expect(appendTier2(local, corpus).map((h) => [h.identity, h.tier])).toEqual([
      ['https://local.example/', 'local'],
      ['https://only-in-text.example/', 'corpus'],
    ]);
  });

  it('Given tier-1 has tier2_min_hits hits and a best score at tier2_min_score, When deciding, Then tier-2 is not requested', () => {
    const { tier2_min_hits, tier2_min_score } = TIER2_THRESHOLDS;
    const local = Array.from({ length: tier2_min_hits }, (_, i) => hit(`https://l${i}.example/`, i === 0 ? tier2_min_score : 0.1, 'local'));
    expect(shouldRequestTier2(local)).toBe(false);
  });

  it('Given enough tier-1 hits whose best score is under tier2_min_score, When deciding, Then tier-2 is requested', () => {
    const { tier2_min_hits, tier2_min_score } = TIER2_THRESHOLDS;
    const local = Array.from({ length: tier2_min_hits + 2 }, (_, i) => hit(`https://l${i}.example/`, tier2_min_score - 0.01, 'local'));
    expect(shouldRequestTier2(local)).toBe(true);
  });

  it('Given thresholds passed as named parameters, When deciding, Then they replace the defaults', () => {
    const local = [hit('https://a.example/', 0.95, 'local')];
    expect(shouldRequestTier2(local, { tier2_min_hits: 1, tier2_min_score: 0.9 })).toBe(false);
    expect(shouldRequestTier2(local, { tier2_min_hits: 2, tier2_min_score: 0.9 })).toBe(true);
  });

  it('Given a query, When requested, Then one valid contract v1 search frame carries it, with a page limit', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(corpusDaemon);
    await searchRemote('tokio', { transport, ids: new SequentialIdSource() }, { limit: 20 });
    expect(transport.sent).toHaveLength(1);
    expect(SearchSchema.parse(transport.sent[0])).toMatchObject({ query: 'tokio', limit: 20 });
  });

  it('Given a query over 1,024 code points holding a lone surrogate, When requested, Then the sent query is well-formed and cut to the cap', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(corpusDaemon);
    await searchRemote('\uDC00' + 'q'.repeat(2000), { transport, ids: new SequentialIdSource() });
    const frame = SearchSchema.parse(transport.sent[0]);
    expect([...frame.query]).toHaveLength(1024);
    expect(frame.query.startsWith('�')).toBe(true);
  });

  it('Given a blank query, When requested, Then nothing is sent and there are no hits', async () => {
    const transport = new FakeTransport();
    expect(await searchRemote('  ', { transport, ids: new SequentialIdSource() })).toEqual([]);
    expect(transport.sent).toEqual([]);
  });

  it('Given the daemon answers error, When requested, Then it rejects with a DaemonError', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'version_mismatch', message: 'read-only' }));
    await expect(searchRemote('tokio', { transport, ids: new SequentialIdSource() })).rejects.toBeInstanceOf(DaemonError);
  });
});
