// move.ts -- observed tree moves and the feedback they become (design, "Move",
// "MoveFeedback").

import type { FolderPath } from './tree.js';
import type { EpochMs, NodeId, Url } from './values.js';

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
