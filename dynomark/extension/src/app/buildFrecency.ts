// buildFrecency.ts -- Frecency for the LocalIndex (design glossary: identity
// -> visit boost derived from browser history through HistoryPort). History
// is asked by each identity the index holds, exactly (contract v1,
// "Identity"): the extension never normalizes a URL.

import { frecencyOf, type Frecency, type LocalIndex } from '../domain/search.js';
import type { Identity } from '../domain/values.js';
import type { Clock } from '../ports/clock.js';
import type { HistoryPort } from '../ports/history.js';

// --- Flow ---

/** A boost per identity in the index that has any visit. */
export async function buildFrecency(index: LocalIndex, deps: { readonly history: HistoryPort; readonly clock: Clock }): Promise<Frecency> {
  const now = deps.clock.now();
  const identities = [...new Set(index.map((row) => row.identity))];
  const boosts = await Promise.all(identities.map(async (id) => [id, frecencyOf(await deps.history.visitsTo(id), now)] as const));
  return new Map<Identity, number>(boosts.filter(([, boost]) => boost > 0));
}
