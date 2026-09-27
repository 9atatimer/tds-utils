// search.ts -- queries, hits, the LocalIndex and frecency (design, "Query /
// Hit", "LocalIndex", "Frecency").

import { MAX_INDEX_ROW_BYTES, utf8Length } from './limits.js';
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

// --- Tier 2 ---

/** When tier 1 is not enough: fewer hits than `tier2_min_hits`, or a best score under `tier2_min_score`. */
export interface Tier2Thresholds {
  readonly tier2_min_hits: number;
  readonly tier2_min_score: number;
}

/** The design's named parameters, with their values in code. */
export const TIER2_THRESHOLDS: Tier2Thresholds = { tier2_min_hits: 3, tier2_min_score: 0.7 };

/** True when tier 1 returned fewer than `tier2_min_hits` hits or its best score is under `tier2_min_score`. */
export function shouldRequestTier2(tier1: readonly Hit[], thresholds: Tier2Thresholds = TIER2_THRESHOLDS): boolean {
  if (tier1.length < thresholds.tier2_min_hits) return true;
  return Math.max(...tier1.map((h) => h.score)) < thresholds.tier2_min_score;
}

/** Tier-2 hits appended below tier 1, leaving out any identity tier 1 already shows. */
export function appendTier2(tier1: readonly Hit[], tier2: readonly Hit[]): Hit[] {
  const shown = new Set(tier1.map((h) => h.identity));
  return [...tier1, ...tier2.filter((h) => !shown.has(h.identity))];
}

// --- LocalIndex ---

/** True when the row, as compact UTF-8 JSON, is within the contract's 512 bytes. */
export function fitsIndexRow(row: LocalIndexRow): boolean {
  return utf8Length(JSON.stringify(row)) <= MAX_INDEX_ROW_BYTES;
}

/** One row per identity across the pulled pages (a later row replaces an earlier one), oversize rows left out. */
export function toLocalIndex(rows: readonly LocalIndexRow[]): LocalIndex {
  const byIdentity = new Map<Identity, LocalIndexRow>();
  for (const row of rows) if (fitsIndexRow(row)) byIdentity.set(row.identity, row);
  return [...byIdentity.values()];
}
