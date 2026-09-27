// move.ts -- observed tree moves and the feedback they become (design, "Move",
// "MoveFeedback"; Behaviors row "A user move becomes feedback").

import type { WriteBatch } from './batch.js';
import { isPathInside } from './paths.js';
import type { HostRole } from './roles.js';
import type { FolderPath, OwnedRoots } from './tree.js';
import type { EpochMs, NodeId, Url } from './values.js';

// --- Types ---

/** `extension` when the move was one of the batch operations the extension itself issued; else `user`. */
export type MoveOrigin = 'user' | 'extension';

/** An observed move of one node between two folders. */
export interface Move {
  readonly node_id: NodeId;
  readonly url?: Url;
  readonly from: FolderPath;
  readonly to: FolderPath;
  readonly origin: MoveOrigin;
  readonly observed_at: EpochMs;
}

/** A `Move` of origin `user` between two owned folders, on the writer host: a labelled placement example. */
export type MoveFeedback = Move & { readonly origin: 'user' };

// --- Predicates ---

function isOwnedPath(path: FolderPath, roots: OwnedRoots): boolean {
  return [roots.follow_up, roots.dynomark, roots.graveyard].some((root) => isPathInside(path, root));
}

/** True when both the source and the destination lie inside an owned root: the only moves record_move sees. */
export function isOwnedMove(from: FolderPath, to: FolderPath, roots: OwnedRoots): boolean {
  return isOwnedPath(from, roots) && isOwnedPath(to, roots);
}

function isFeedback(move: Move, role: HostRole): move is MoveFeedback {
  return move.origin === 'user' && role === 'writer';
}

// --- Pure helpers ---

/** The nodes an in-flight batch moves itself: those its move and remove ops name. */
export function inFlightNodes(batch: WriteBatch): Set<NodeId> {
  return new Set(batch.operations.flatMap((op) => (op.op === 'move' || op.op === 'remove' ? [op.node_id] : [])));
}

/** `extension` for a node the in-flight batch names, else `user`. */
export function moveOrigin(node_id: NodeId, inFlight: ReadonlySet<NodeId>): MoveOrigin {
  return inFlight.has(node_id) ? 'extension' : 'user';
}

/** record_move: a user move on the writer is feedback; an extension move, or any move on a reader, is none. */
export function recordMove(move: Move, role: HostRole): MoveFeedback | undefined {
  return isFeedback(move, role) ? move : undefined;
}
