// searchLocal.ts -- use case "Tier-1 search" (design, Behaviors and
// Interfaces): search_local(query, index, frecency) -> list[Hit]. No port and
// no transport call: the whole rule is the domain's ranking; this is its
// name at the use-case surface.

import { rankLocal, type Tier1Options } from '../domain/ranking.js';
import type { Frecency, Hit, LocalIndex, Query } from '../domain/search.js';

// --- Flow ---

/** Tier-1 suggestions for a keystroke, best first. `options` carries the owned roots (for the bonus) and a limit. */
export function searchLocal(query: Query, index: LocalIndex, frecency: Frecency, options: Tier1Options = {}): Hit[] {
  return rankLocal(query, index, frecency, options);
}
