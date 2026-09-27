// pendingMoves.ts -- the move reports sent and not yet answered
// move.observed.result (contract v1, "Delivery and replay": a request with no
// answer is re-sent after a reconnect, and busy and internal are retried,
// with the same id and body). Kept so a worker that dies before the answer
// leaves the report to the next, rather than losing the feedback. Bounded:
// the oldest go first.

import type { Move } from './move.js';
import type { RequestId } from './values.js';

// --- Types ---

/** One move.observed request as sent: its id and the move it reported. */
export interface PendingMove {
  readonly id: RequestId;
  readonly move: Move;
}

// --- Constants ---

/** At most this many move reports are kept pending at once. */
export const MAX_PENDING_MOVES = 64;

// --- Pure helpers ---

/** `moves` with `pending` kept last (in place of any with its id), the oldest dropped past the bound. */
export function withPendingMove(moves: readonly PendingMove[], pending: PendingMove): PendingMove[] {
  const next = [...moves.filter((kept) => kept.id !== pending.id), pending];
  return next.slice(Math.max(0, next.length - MAX_PENDING_MOVES));
}

/** `moves` without the request `id`. */
export function withoutPendingMove(moves: readonly PendingMove[], id: RequestId): PendingMove[] {
  return moves.filter((kept) => kept.id !== id);
}
