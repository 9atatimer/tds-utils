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
