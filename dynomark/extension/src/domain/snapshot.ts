// snapshot.ts -- the tree as it may leave the extension (design, "Snapshot";
// contract v1 README, "Size limits" and "Framing"): every title and url made
// well-formed and cut to its cap, and a node whose title or url was cut is
// marked `truncated`.

import { MAX_TITLE, MAX_URL, fitText } from './limits.js';
import type { Snapshot, SnapshotNode, TreeRead } from './tree.js';
import type { EpochMs } from './values.js';

// --- Pure helpers ---

function fitNode(node: SnapshotNode): SnapshotNode {
  const title = fitText(node.title, MAX_TITLE);
  const url = node.kind === 'bookmark' ? fitText(node.url, MAX_URL) : undefined;
  const truncated = title.truncated || (url?.truncated ?? false) || node.truncated === true;
  const base = { ...node, title: title.text, ...(truncated ? { truncated: true as const } : {}) };
  return url === undefined ? base : { ...base, kind: 'bookmark', url: url.text };
}

/** The tree read at `taken_at`, fit for the wire. */
export function toSnapshot(read: TreeRead, taken_at: EpochMs): Snapshot {
  return { taken_at, root_ids: read.root_ids, nodes: read.nodes.map(fitNode) };
}
