// buildFrecency.ts -- Frecency for the LocalIndex (design glossary: identity
// -> visit boost derived from browser history through HistoryPort). History
// is asked by each identity the index holds, exactly (contract v1,
// "Identity"): the extension never normalizes a URL.

import { frecencyOf, type Frecency, type LocalIndex, type Visit } from '../domain/search.js';
import type { Identity } from '../domain/values.js';
import type { Clock } from '../ports/clock.js';
import type { HistoryPort } from '../ports/history.js';

// --- Constants ---

/** History lookups in flight at once: a 10,000-entry index must not ask the browser 10,000 things at the same moment. */
export const HISTORY_CONCURRENCY = 32;

// --- Flow ---

/** A boost per identity in the index that has any visit; an identity whose lookup fails gets none. */
export async function buildFrecency(index: LocalIndex, deps: { readonly history: HistoryPort; readonly clock: Clock }): Promise<Frecency> {
  const now = deps.clock.now();
  const identities = [...new Set(index.map((row) => row.identity))];
  const boosts = new Map<Identity, number>();
  const queue = identities.values(); // shared by every lane: each identity is asked once
  const lane = async (): Promise<void> => {
    for (const id of queue) {
      const boost = frecencyOf(await deps.history.visitsTo(id).catch((): readonly Visit[] => []), now);
      if (boost > 0) boosts.set(id, boost);
    }
  };
  await Promise.all(Array.from({ length: Math.min(HISTORY_CONCURRENCY, identities.length) }, lane));
  return boosts;
}
