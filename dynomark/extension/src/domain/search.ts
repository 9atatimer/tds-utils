// search.ts -- queries, hits, the LocalIndex and frecency (design, "Query /
// Hit", "LocalIndex", "Frecency").

import type { FolderPath } from './tree.js';
import type { EpochMs, Identity, Title } from './values.js';

/** A search string as the user typed it. */
export type Query = string;

/** `local`: from the LocalIndex (tier 1). `corpus`: from the daemon (tier 2). */
export type HitTier = 'local' | 'corpus';

/** A ranked match; `score` is in [0, 1]. */
export interface Hit {
  readonly identity: Identity;
  readonly title: Title;
  readonly path: FolderPath;
  readonly score: number;
  readonly tier: HitTier;
}

/** One entry of the LocalIndex: at most 512 bytes as compact JSON, pulled from the daemon. */
export interface LocalIndexRow {
  readonly identity: Identity;
  readonly title: Title;
  readonly path: FolderPath;
  readonly tags: readonly string[];
  readonly summary: string;
}

/** The rebuildable per-entry index tier-1 search runs over. */
export type LocalIndex = readonly LocalIndexRow[];

/** One visit to a URL, as browser history reports it. */
export interface Visit {
  readonly visited_at: EpochMs;
}

/** Identity -> visit boost derived from history. */
export type Frecency = ReadonlyMap<Identity, number>;

// --- Frecency ---

const DAY_MS = 86_400_000;

/** Visit weight by age, newest bucket first (the shape of Firefox's frecency buckets). */
const AGE_WEIGHTS: readonly (readonly [maxAgeMs: number, weight: number])[] = [
  [4 * DAY_MS, 100],
  [14 * DAY_MS, 70],
  [31 * DAY_MS, 50],
  [90 * DAY_MS, 30],
];
const OLDEST_WEIGHT = 10;
/** Only the most recent visits count, so a long history cannot drown recency. */
const SAMPLED_VISITS = 10;

function visitWeight(visit: Visit, now: EpochMs): number {
  const age = Math.max(0, now - visit.visited_at);
  return AGE_WEIGHTS.find(([maxAge]) => age <= maxAge)?.[1] ?? OLDEST_WEIGHT;
}

/** The boost of one identity: the age-weighted sum over its most recent visits; 0 with none. */
export function frecencyOf(visits: readonly Visit[], now: EpochMs): number {
  return [...visits]
    .sort((a, b) => b.visited_at - a.visited_at)
    .slice(0, SAMPLED_VISITS)
    .reduce((sum, v) => sum + visitWeight(v, now), 0);
}
