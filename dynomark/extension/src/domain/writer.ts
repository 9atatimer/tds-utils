// writer.ts -- the writer marker as the daemon reports it (design, Key
// Decisions "Two writers": MVP, refuse on a writer marker in the owned tree;
// contract v1, "Writer marker (MVP)").

import type { HostRole } from './roles.js';
import type { HostId } from './values.js';

/** What writer.status reports: this host's role, whether its marker is in the tree, and other writers' markers. */
export interface WriterStatus {
  readonly role: HostRole;
  readonly host_id: HostId;
  readonly own_marker: boolean;
  readonly other_writers: readonly HostId[];
  /** A writer that sees another host's marker: it files nothing until the stale marker is removed. */
  readonly conflict: boolean;
}
