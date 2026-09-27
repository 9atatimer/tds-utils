// onConnected.ts -- the connect routine after a hello (contract v1 README,
// "Connection lifecycle", step 4; "Index freshness"): in full mode send
// tree.snapshot and events.replay, then pull the index; in read_only replay
// events and pull the index (search continues); in refused, nothing.

import { MAX_FRAME_TO_DAEMON_BYTES, utf8Length } from '../domain/limits.js';
import { toSnapshot } from '../domain/snapshot.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { Clock } from '../ports/clock.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import type { HelloOutcome } from './connection.js';
import { resultOrThrow } from './errors.js';
import { syncIndex } from './syncIndex.js';

// --- Types ---

export interface ConnectedDeps {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly tree: BookmarkTreePort;
  readonly clock: Clock;
  readonly storage: StoragePort;
}

// --- Flow ---

/** Send the tree as read now; a snapshot whose frame would exceed 32 MiB is not sent (so no batch is offered). */
export async function sendTreeSnapshot(deps: Omit<ConnectedDeps, 'storage'>): Promise<void> {
  const frame = {
    v: CONTRACT_VERSION,
    type: 'tree.snapshot',
    id: deps.ids.next(),
    snapshot: toSnapshot(await deps.tree.readTree(), deps.clock.now()),
  } as const;
  if (utf8Length(JSON.stringify(frame)) > MAX_FRAME_TO_DAEMON_BYTES) return;
  resultOrThrow(await deps.transport.send(frame));
}

async function replayEvents(deps: ConnectedDeps): Promise<void> {
  resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'events.replay', id: deps.ids.next() }));
}

/** The connect routine for the mode hello.result decided. */
export async function onConnected(outcome: HelloOutcome, deps: ConnectedDeps): Promise<void> {
  if (outcome.mode === 'refused') return;
  if (outcome.mode === 'full') await sendTreeSnapshot(deps);
  await replayEvents(deps);
  await syncIndex(deps);
}
