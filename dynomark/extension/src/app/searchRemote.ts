// searchRemote.ts -- use case "Tier-2 search is requested" (design, Behaviors
// and Interfaces): search_remote(query, *, transport) -> list[Hit]. One page
// of the daemon's corpus hits (tier corpus); whether to ask at all is the
// domain's shouldRequestTier2, and the caller appends with appendTier2.

import { MAX_QUERY, fitText } from '../domain/limits.js';
import type { Hit, Query } from '../domain/search.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';

// --- Constants ---

/** Hits asked for in one page (the contract caps a search page at 100). */
export const DEFAULT_TIER2_LIMIT = 20;

// --- Flow ---

/** The first page of corpus hits for the query; nothing is sent for a blank query. */
export async function searchRemote(
  query: Query,
  deps: { readonly transport: TransportPort; readonly ids: IdSource },
  options: { readonly limit?: number } = {},
): Promise<Hit[]> {
  const text = fitText(query.trim(), MAX_QUERY).text;
  if (text === '') return [];
  const frame = {
    v: CONTRACT_VERSION,
    type: 'search',
    id: deps.ids.next(),
    query: text,
    limit: options.limit ?? DEFAULT_TIER2_LIMIT,
  } as const;
  const result = resultOrThrow(await deps.transport.send(frame));
  return [...result.hits];
}
