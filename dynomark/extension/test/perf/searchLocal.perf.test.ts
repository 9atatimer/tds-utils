// searchLocal.perf.test.ts -- Goal 4 (design): "tier-1 suggestions render
// within 20 ms (P95) of a keystroke at 10,000 entries", and the Behaviors row
// "Tier-1 search": "Given 10,000 entries ... the call is within Goal 4's
// tier-1 bound".
//
// A wall-clock claim, so it lives outside the shuffled, parallel unit tier:
// `npm test` runs this tier after that one, one file at a time, with its own
// timeout. The claim is about this code on a runner able to measure it: a
// fixed CPU workload runs right before every sample, and when that
// workload's own P95 is over its budget the runner was too slow or too busy
// while sampling, so the test skips instead of failing.

import { describe, expect, it } from 'vitest';
import { searchLocal } from '../../src/app/searchLocal.js';
import type { Frecency, LocalIndexRow } from '../../src/domain/search.js';
import type { FolderPath, OwnedRoots } from '../../src/domain/tree.js';

// --- Builders ---

const ROOTS: OwnedRoots = {
  follow_up: { root: 'bar', names: ['Follow Up'] },
  dynomark: { root: 'bar', names: ['Dynomark'] },
  graveyard: { root: 'bar', names: ['Graveyard'] },
};

const ELSEWHERE: FolderPath = { root: 'other', names: ['Imported'] };
const FILED: FolderPath = { root: 'bar', names: ['Dynomark', 'Rust'] };

const ENTRIES = 10_000;
const BUDGET_MS = 20;
const RUNS = 21;
/** The fixed workload's P95, taken between samples, on a runner fit to measure the goal. */
const CALIBRATION_BUDGET_MS = 25;

function bigIndex(): LocalIndexRow[] {
  const words = ['async', 'rust', 'tokio', 'serde', 'python', 'kernel', 'bookmarks', 'design', 'review', 'garden', 'cloud', 'budget'];
  return Array.from({ length: ENTRIES }, (_, i) => {
    const w = (k: number) => words[(i * 7 + k * 3) % words.length] ?? 'x';
    return {
      identity: `https://e${i}.example/`,
      title: `${w(0)} ${w(1)} notes ${i}`,
      path: i % 2 === 0 ? FILED : ELSEWHERE,
      tags: [w(2), w(3)],
      summary: `A page about ${w(4)} and ${w(5)} with ${w(6)}; entry ${i} of the corpus, kept for later reading.`.repeat(3),
    };
  });
}

function calibrationMs(): number {
  const text = 'the quick brown fox jumps over the lazy dog '.repeat(50_000);
  const start = performance.now();
  let found = 0;
  for (let i = 0; i < 10; i += 1) found += text.toLowerCase().indexOf(`zebra${i}`);
  if (found === 0) throw new Error('unreachable: calibration result is used');
  return performance.now() - start;
}

function p95(samples: number[]): number {
  const sorted = [...samples].sort((a, b) => a - b);
  return sorted[Math.ceil(sorted.length * 0.95) - 1] ?? Number.POSITIVE_INFINITY;
}

// --- Tests ---

describe('Goal 4: tier-1 suggestions within 20 ms (P95) at 10,000 entries', () => {
  it('Given 10,000 entries, When queried repeatedly, Then the P95 call time is within the budget (skipped on a runner too slow to measure it)', (ctx) => {
    const index = bigIndex();
    const frecency: Frecency = new Map(index.slice(0, 2000).map((r, i) => [r.identity, i]));
    const queries = ['tokio', 'async rust', 'serde notes', 'kernl', 'budget cloud', 'garden 42', 'bookmarks design'];
    // Warm-up: one pass over every query, so the JIT has compiled the path being measured (steady state, as on every keystroke).
    for (const q of [...queries, ...queries]) searchLocal(q, index, frecency, { owned_roots: ROOTS });
    const calibrations: number[] = [];
    const samples = Array.from({ length: RUNS }, (_, i) => {
      calibrations.push(calibrationMs());
      const start = performance.now();
      searchLocal(queries[i % queries.length] ?? 'rust', index, frecency, { owned_roots: ROOTS });
      return performance.now() - start;
    });
    const observed = p95(samples);
    const calibration = p95(calibrations);
    if (observed > BUDGET_MS && calibration > CALIBRATION_BUDGET_MS) {
      ctx.skip(
        `runner too slow to measure Goal 4: P95 ${observed.toFixed(1)} ms, calibration P95 ${calibration.toFixed(1)} ms over ${CALIBRATION_BUDGET_MS} ms`,
      );
    }
    expect(observed).toBeLessThanOrEqual(BUDGET_MS);
  });
});
