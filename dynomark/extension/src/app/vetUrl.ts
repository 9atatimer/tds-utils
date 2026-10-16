// vetUrl.ts -- before the writer opens a background tab, the daemon vets the
// URL against its fetch address policy (design, Key Decisions "Background-tab
// capture" 2026-10-16, issue #410; contract v2 README, "Background-tab
// capture"). The daemon resolves DNS, which the extension cannot.

import type { Url } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';

// --- Flow ---

/**
 * True only when the daemon answers url.vet with allowed true. A refusal is
 * false; an error answer or a lost link rejects (the caller treats both as a
 * refusal: the tab is never opened).
 */
export async function vetUrl(url: Url, deps: { readonly transport: TransportPort; readonly ids: IdSource }): Promise<boolean> {
  const result = resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'url.vet', id: deps.ids.next(), url }));
  return result.allowed;
}
