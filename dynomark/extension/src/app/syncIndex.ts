// syncIndex.ts -- use case "The local index is synced" (design, Behaviors and
// Interfaces): sync_index(*, transport) -> LocalIndex. Pulls every page of
// the daemon's LocalIndex from the first, and swaps it into storage only
// when the last page arrives (contract v1, "Index freshness", "Pagination").

import { toLocalIndex, type LocalIndex, type LocalIndexRow } from '../domain/search.js';
import type { Cursor } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { DaemonError } from './errors.js';

// --- Constants ---

/** Rows asked for per page (the contract's cap for index.pull). */
export const DEFAULT_INDEX_PAGE_LIMIT = 1000;
/** How many times a stale_cursor restarts the pull before the sync gives up. */
export const MAX_PULL_RESTARTS = 3;

// --- Types ---

export interface SyncDeps {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly storage: StoragePort;
}

/** A page's cursor went stale: the pull starts again from the first page. */
class StaleCursor {
  readonly error: DaemonError;

  constructor(error: DaemonError) {
    this.error = error;
  }
}

// --- Flow ---

async function pullPage(cursor: Cursor | undefined, limit: number, deps: SyncDeps) {
  const frame = {
    v: CONTRACT_VERSION,
    type: 'index.pull',
    id: deps.ids.next(),
    limit,
    ...(cursor === undefined ? {} : { cursor }),
  } as const;
  const response = await deps.transport.send(frame);
  if (response.type !== 'error') return response;
  const error = new DaemonError(response);
  return error.code === 'stale_cursor' ? new StaleCursor(error) : Promise.reject(error);
}

/** Every page from the first; a StaleCursor when a page's cursor has expired. */
async function pullAll(limit: number, deps: SyncDeps): Promise<LocalIndexRow[] | StaleCursor> {
  const rows: LocalIndexRow[] = [];
  let cursor: Cursor | undefined;
  do {
    const page = await pullPage(cursor, limit, deps);
    if (page instanceof StaleCursor) return page;
    rows.push(...page.rows);
    cursor = page.next_cursor ?? undefined;
  } while (cursor !== undefined);
  return rows;
}

/** Pull the whole LocalIndex and store it; the stored index changes only when the last page has arrived. */
export async function syncIndex(deps: SyncDeps, options: { readonly page_limit?: number } = {}): Promise<LocalIndex> {
  const limit = options.page_limit ?? DEFAULT_INDEX_PAGE_LIMIT;
  for (let restarts = 0; ; restarts += 1) {
    const pulled = await pullAll(limit, deps);
    if (pulled instanceof StaleCursor) {
      if (restarts >= MAX_PULL_RESTARTS) throw pulled.error;
      continue;
    }
    const index = toLocalIndex(pulled);
    await deps.storage.saveLocalIndex(index);
    return index;
  }
}
