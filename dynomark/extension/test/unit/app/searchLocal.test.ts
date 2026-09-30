// searchLocal.test.ts -- design Behaviors row "Tier-1 search":
// search_local(query, index, frecency) -> list[Hit]. Title matches form a
// hard tier above path, tag and summary matches; within a tier, fuzzy score
// then frecency (design, "The extension"); an entry filed under the owned
// Dynomark folder gets a bonus (task-024); no transport call. Goal 4's
// tier-1 bound (20 ms P95 at 10,000 entries) is timed in test/perf, a tier
// run serially after this one.

import { describe, expect, it } from 'vitest';
import { searchLocal } from '../../../src/app/searchLocal.js';
import type { Frecency, Hit, LocalIndexRow } from '../../../src/domain/search.js';
import type { FolderPath, OwnedRoots } from '../../../src/domain/tree.js';

// --- Builders ---

const ROOTS: OwnedRoots = {
  follow_up: { root: 'bar', names: ['Follow Up'] },
  dynomark: { root: 'bar', names: ['Dynomark'] },
  graveyard: { root: 'bar', names: ['Graveyard'] },
};

const ELSEWHERE: FolderPath = { root: 'other', names: ['Imported'] };
const FILED: FolderPath = { root: 'bar', names: ['Dynomark', 'Rust'] };

function row(identity: string, title: string, extra: Partial<LocalIndexRow> = {}): LocalIndexRow {
  return { identity: `https://${identity}/`, title, path: ELSEWHERE, tags: [], summary: '', ...extra };
}

function identities(hits: readonly Hit[]): string[] {
  return hits.map((h) => h.identity);
}

const NO_FRECENCY: Frecency = new Map();

// --- Tests ---

describe('Behavior: Tier-1 search -- searchLocal(query, index, frecency)', () => {
  it('Given title, path, tag and summary matches, When queried, Then every title match precedes every non-title match', () => {
    const index = [
      row('summary.example', 'Unrelated', { summary: 'tokio' }),
      row('fuzzy-title.example', 'The Tao of Kilo Ordinals'),
      row('tag.example', 'Other', { tags: ['tokio'] }),
      row('path.example', 'Else', { path: { root: 'bar', names: ['Dynomark', 'Tokio'] } }),
      row('title.example', 'Tokio tutorial'),
    ];
    const hits = searchLocal('tokio', index, new Map([['https://summary.example/', 1000]]));
    const tiers = hits.map((h) => (h.title.toLowerCase().includes('tokio') || h.title.startsWith('The Tao') ? 'title' : 'other'));
    expect(identities(hits).slice(0, 2)).toEqual(['https://title.example/', 'https://fuzzy-title.example/']);
    expect(tiers).toEqual(['title', 'title', 'other', 'other', 'other']);
  });

  it('Given two titles of equal fuzzy score, When queried, Then the one with the higher frecency ranks first', () => {
    const index = [row('rarely.example', 'Serde guide'), row('often.example', 'Serde guide')];
    const frecency = new Map([
      ['https://rarely.example/', 10],
      ['https://often.example/', 90],
    ]);
    expect(identities(searchLocal('serde', index, frecency))).toEqual(['https://often.example/', 'https://rarely.example/']);
  });

  it('Given a better fuzzy score and a higher frecency on different titles, When queried, Then fuzzy score decides before frecency', () => {
    const index = [row('exact.example', 'serde'), row('popular.example', 'Serialize and deserialize')];
    const frecency = new Map([['https://popular.example/', 10_000]]);
    expect(identities(searchLocal('serde', index, frecency))[0]).toBe('https://exact.example/');
  });

  it('Given equal titles, one filed under Dynomark and one elsewhere with more visits, When queried with the owned roots, Then the owned one ranks first', () => {
    const index = [row('elsewhere.example', 'Async Rust'), row('filed.example', 'Async Rust', { path: FILED })];
    const frecency = new Map([['https://elsewhere.example/', 500]]);
    const hits = searchLocal('async', index, frecency, { owned_roots: ROOTS });
    expect(identities(hits)).toEqual(['https://filed.example/', 'https://elsewhere.example/']);
    expect(hits[0]?.score).toBeGreaterThan(hits[1]?.score ?? 1);
  });

  it('Given an owned bonus, When a non-title entry is filed under Dynomark, Then it still ranks below every title match', () => {
    const index = [row('filed.example', 'Else', { path: FILED, summary: 'tokio runtime' }), row('title.example', 'tokio-ish thing')];
    const hits = searchLocal('tokio', index, NO_FRECENCY, { owned_roots: ROOTS });
    expect(identities(hits)).toEqual(['https://title.example/', 'https://filed.example/']);
  });

  it('Given matching entries, When queried, Then each hit is tier local, carries its row identity, title and path, and a score in [0, 1]', () => {
    const hits = searchLocal('rust', [row('a.example', 'Rust Book', { path: FILED }), row('b.example', 'rust')], NO_FRECENCY, {
      owned_roots: ROOTS,
    });
    expect(hits).toHaveLength(2);
    for (const hit of hits) {
      expect(hit.tier).toBe('local');
      expect(hit.score).toBeGreaterThan(0);
      expect(hit.score).toBeLessThanOrEqual(1);
    }
    expect(hits.find((h) => h.identity === 'https://a.example/')).toMatchObject({ title: 'Rust Book', path: FILED });
  });

  it('Given a two-word query, When queried, Then only entries matching both words are hits, whatever the letter case', () => {
    const index = [
      row('both.example', 'ASYNC Rust'),
      row('one.example', 'Async Python'),
      row('split.example', 'Rust', { tags: ['async'] }),
    ];
    expect(identities(searchLocal('async rust', index, NO_FRECENCY)).sort()).toEqual(['https://both.example/', 'https://split.example/']);
  });

  it('Given no entry matches, or a blank query, When queried, Then there are no hits', () => {
    const index = [row('a.example', 'Rust Book')];
    expect(searchLocal('haskell', index, NO_FRECENCY)).toEqual([]);
    expect(searchLocal('   ', index, NO_FRECENCY)).toEqual([]);
  });

  it('Given a limit, When more entries match, Then only that many hits are returned, best first', () => {
    const index = Array.from({ length: 30 }, (_, i) => row(`e${i}.example`, `Rust ${i}`));
    const frecency = new Map([['https://e7.example/', 5]]);
    const hits = searchLocal('rust', index, frecency, { limit: 5 });
    expect(hits).toHaveLength(5);
    expect(hits[0]?.identity).toBe('https://e7.example/');
  });
});
