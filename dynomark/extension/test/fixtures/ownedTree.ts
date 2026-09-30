// ownedTree.ts -- a Chrome-shaped profile with Dynomark's owned roots under
// the bookmarks bar, seeded through the tree fake, plus the connection
// context (owned_roots, host_id) a hello.result would give the extension.

import type { BatchContext } from '../../src/app/applyBatch.js';
import type { FolderPath, OwnedRoots } from '../../src/domain/tree.js';
import type { NodeId } from '../../src/domain/values.js';
import type { FakeBookmarkTree } from '../fakes/FakeBookmarkTree.js';

// --- Constants ---

export const FOLLOW_UP: FolderPath = { root: 'bar', names: ['Follow Up'] };
export const DYNOMARK: FolderPath = { root: 'bar', names: ['Dynomark'] };
export const GRAVEYARD: FolderPath = { root: 'bar', names: ['Graveyard'] };
export const RUST: FolderPath = { root: 'bar', names: ['Dynomark', 'Rust'] };

export const ROOTS: OwnedRoots = { follow_up: FOLLOW_UP, dynomark: DYNOMARK, graveyard: GRAVEYARD };
export const HOST_ID = 'mbp';
export const CONTEXT: BatchContext = { owned_roots: ROOTS, host_id: HOST_ID };

// --- Types ---

/** The node ids of the seeded tree. */
export interface Seeded {
  readonly bar: NodeId;
  readonly followUp: NodeId;
  readonly dynomark: NodeId;
  readonly graveyard: NodeId;
  readonly rust: NodeId;
  /** A bookmark just saved into Follow Up. */
  readonly saved: NodeId;
  /** A bookmark of the user's own, directly on the bar (outside every owned root). */
  readonly usersOwn: NodeId;
}

// --- Builders ---

/** Seed Follow Up (holding one saved bookmark), Dynomark/Rust and Graveyard under the bar, and one user bookmark on the bar. */
export async function seedOwnedTree(tree: FakeBookmarkTree): Promise<Seeded> {
  const bar = (await tree.readTree()).root_ids.bar;
  const followUp = (await tree.createFolder(bar, 'Follow Up')).id;
  const dynomark = (await tree.createFolder(bar, 'Dynomark')).id;
  const graveyard = (await tree.createFolder(bar, 'Graveyard')).id;
  const rust = (await tree.createFolder(dynomark, 'Rust')).id;
  const saved = (await tree.createBookmark(followUp, 'Tokio tutorial', 'https://tokio.rs/tokio/tutorial?utm_source=x')).id;
  const usersOwn = (await tree.createBookmark(bar, 'Mail', 'https://mail.example/')).id;
  return { bar, followUp, dynomark, graveyard, rust, saved, usersOwn };
}
