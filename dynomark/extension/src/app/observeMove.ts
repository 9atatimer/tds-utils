// observeMove.ts -- the extension's "Record feedback" responsibility (design,
// "The extension"): on every onMoved whose source and destination are owned,
// stamp the Move with its origin (extension for nodes the in-flight batch
// names) and the time, report it as move.observed, and apply record_move.
// The browser adapter turns parent ids into FolderPaths before calling this.

import { fitPath } from '../domain/limits.js';
import { isOwnedMove, moveOrigin, type Move, type MoveFeedback } from '../domain/move.js';
import type { HostRole } from '../domain/roles.js';
import type { FolderPath, OwnedRoots } from '../domain/tree.js';
import type { NodeId, Url } from '../domain/values.js';
import type { Clock } from '../ports/clock.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';
import { recordMove } from './recordMove.js';

// --- Types ---

/** A move as the browser reported it, its parents already expressed as paths. */
export interface ObservedMove {
  readonly node_id: NodeId;
  readonly url?: Url;
  readonly from: FolderPath;
  readonly to: FolderPath;
}

export interface MoveContext {
  readonly owned_roots: OwnedRoots;
  /** The nodes the batch whose cursor is open names (inFlightNodes); empty when none is. */
  readonly in_flight: ReadonlySet<NodeId>;
}

// --- Flow ---

/** Report an owned move to the daemon and return the feedback it is, if any; a move outside the owned roots is ignored. */
export async function observeMove(
  observed: ObservedMove,
  role: HostRole,
  context: MoveContext,
  deps: { readonly transport: TransportPort; readonly ids: IdSource; readonly clock: Clock },
): Promise<MoveFeedback | undefined> {
  if (!isOwnedMove(observed.from, observed.to, context.owned_roots)) return undefined;
  const move: Move = {
    ...observed,
    from: fitPath(observed.from),
    to: fitPath(observed.to),
    origin: moveOrigin(observed.node_id, context.in_flight),
    observed_at: deps.clock.now(),
  };
  resultOrThrow(await deps.transport.send({ v: CONTRACT_VERSION, type: 'move.observed', id: deps.ids.next(), move }));
  return recordMove(move, role);
}
