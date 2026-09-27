// recordMove.ts -- use case "A user move becomes feedback" (design, Behaviors
// and Interfaces): record_move(move, role) -> MoveFeedback or none. No port:
// the rule is the domain's isFeedback; observeMove is the workflow that
// stamps a browser move and reports it before asking this.

import { isFeedback, type Move, type MoveFeedback } from '../domain/move.js';
import type { HostRole } from '../domain/roles.js';

// --- Flow ---

/** A user move on the writer is feedback; an extension move, or any move on a reader, is none. */
export function recordMove(move: Move, role: HostRole): MoveFeedback | undefined {
  return isFeedback(move, role) ? move : undefined;
}
