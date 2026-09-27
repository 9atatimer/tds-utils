// issuedMoves.ts -- the tree moves the extension itself made and the browser
// has not reported yet (design, "Move": the extension adapter sets origin from
// the batch operations it itself issued). A node can be moved twice by one
// batch, so each entry is one move: the node and its destination; a move
// re-issued after a kill is remembered once. Bounded: the oldest is forgotten
// first (its report never came).

import type { NodeId } from './values.js';

// --- Types ---

/** One move the extension made: the node and the folder it was moved into. */
export interface IssuedMove {
  readonly node_id: NodeId;
  readonly parent_id: NodeId;
}

// --- Constants ---

/** At most this many issued moves are remembered at once. */
export const MAX_ISSUED_MOVES = 256;

// --- Pure helpers ---

/**
 * `moves` with `move` remembered last, the oldest dropped past the bound.
 * When the latest remembered move of that node is already into that folder,
 * `moves` is unchanged: the batch lane never moves a node into the folder it
 * is in, so this is the same move re-issued by a resumed batch after a kill
 * between remembering it and making it, and the browser reports it once.
 */
export function withIssued(moves: readonly IssuedMove[], move: IssuedMove): IssuedMove[] {
  const latest = [...moves].reverse().find((m) => m.node_id === move.node_id);
  if (latest?.parent_id === move.parent_id) return [...moves];
  const next = [...moves, move];
  return next.slice(Math.max(0, next.length - MAX_ISSUED_MOVES));
}

/** `moves` without the oldest entry for this node and destination; undefined when there is none. */
export function withoutIssued(moves: readonly IssuedMove[], move: IssuedMove): IssuedMove[] | undefined {
  const at = moves.findIndex((m) => m.node_id === move.node_id && m.parent_id === move.parent_id);
  return at < 0 ? undefined : moves.filter((_, i) => i !== at);
}
