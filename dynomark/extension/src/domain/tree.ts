// tree.ts -- the browser bookmark tree as the domain sees it (design,
// "Ubiquitous language": Bookmark, FolderPath, OwnedRoots, Snapshot).

import type { EpochMs, NodeId, Title, Url } from './values.js';

// --- Constants ---

/** The top-level folders a `FolderPath` can start from. Chrome: bar/other/mobile; Firefox adds menu. */
export const ROOT_KEYS = ['bar', 'other', 'mobile', 'menu'] as const;

// --- Types ---

export type RootKey = (typeof ROOT_KEYS)[number];

/** Ordered folder names downward from a top-level folder. `names: []` is the top-level folder itself. */
export interface FolderPath {
  readonly root: RootKey;
  readonly names: readonly Title[];
}

/** The three folders Dynomark owns: a value passed to the boundary policy, never a literal inside it. */
export interface OwnedRoots {
  readonly follow_up: FolderPath;
  readonly dynomark: FolderPath;
  readonly graveyard: FolderPath;
}

/** A URL plus title at a `FolderPath`, with this profile's node id. Its cross-host `Identity` is the daemon's to compute. */
export interface Bookmark {
  readonly node_id: NodeId;
  readonly url: Url;
  readonly title: Title;
  readonly path: FolderPath;
  readonly date_added: EpochMs;
}

export type NodeKind = 'folder' | 'bookmark' | 'separator';

interface SnapshotNodeBase {
  readonly id: NodeId;
  /** null only for the browser's own root node. */
  readonly parent_id: NodeId | null;
  /** Position among its siblings. */
  readonly index: number;
  readonly title: string;
  /** Set when the title or url was cut to its cap before sending. */
  readonly truncated?: true;
  readonly date_added: EpochMs;
}

export interface SnapshotFolder extends SnapshotNodeBase {
  readonly kind: 'folder';
}

export interface SnapshotBookmark extends SnapshotNodeBase {
  readonly kind: 'bookmark';
  readonly url: string;
}

export interface SnapshotSeparator extends SnapshotNodeBase {
  readonly kind: 'separator';
}

/** One node of the tree as the extension read it. Only a bookmark carries a url. */
export type SnapshotNode = SnapshotFolder | SnapshotBookmark | SnapshotSeparator;

/** The node each `RootKey` maps to in this profile (the syncing copy where the browser also keeps a local-only one). */
export interface RootIds {
  readonly bar: NodeId;
  readonly other: NodeId;
  readonly mobile?: NodeId;
  readonly menu?: NodeId;
}

/** The whole tree as read from the browser, before it is stamped with a time. */
export interface TreeRead {
  readonly root_ids: RootIds;
  readonly nodes: readonly SnapshotNode[];
}

/** The full tree as the extension read it at `taken_at`; the fallback export, not the undo mechanism. */
export interface Snapshot extends TreeRead {
  readonly taken_at: EpochMs;
}
