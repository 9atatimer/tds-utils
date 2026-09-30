// backfill.ts -- which existing bookmarks a backfill ingests, and how far it
// got (design, Open Question 3: run the existing tree through capture and
// indexing at first install -- searchable, not re-filed; contract v1, "Jobs":
// a backfill ingest is never offered a batch). Candidates are the http(s)
// bookmarks outside the folders given to skip (Follow Up: those are ordinary
// saves; Graveyard: removed). Progress is a list fixed at the start plus how
// far along it the backfill is, so a restarted worker resumes, and a repeat
// is harmless (ingest is idempotent on node and url). A frame the daemon
// answered busy or internal is kept with it (one at most), so the worker that
// retries it -- this one or the next -- re-sends the same id.

import { isCapturableUrl } from './capture.js';
import { isPathInside } from './paths.js';
import { ROOT_KEYS, type Bookmark, type FolderPath, type SnapshotNode, type TreeRead } from './tree.js';
import type { EpochMs, NodeId, RequestId } from './values.js';

// --- Types ---

/** The ingest at `next_index` as last sent, answered busy or internal: re-sent with this id while its bookmark is unchanged. */
export interface BackfillRetry {
  readonly id: RequestId;
  readonly bookmark: Bookmark;
  /** Retryable answers so far: the backoff attempt of the next retry. */
  readonly attempt: number;
}

export interface BackfillProgress {
  readonly started_at: EpochMs;
  /** The candidates as chosen at the start, in the order they are sent. */
  readonly node_ids: readonly NodeId[];
  /** How many of them have been sent (and answered). */
  readonly next_index: number;
  readonly retry?: BackfillRetry;
}

// --- Pure helpers ---

/** The FolderPath of every folder under a root_ids folder, computed in one pass. */
function folderPaths(tree: TreeRead): Map<NodeId, FolderPath> {
  const children = new Map<NodeId, SnapshotNode[]>();
  for (const node of tree.nodes) {
    if (node.parent_id !== null && node.kind === 'folder') children.set(node.parent_id, [...(children.get(node.parent_id) ?? []), node]);
  }
  const paths = new Map<NodeId, FolderPath>();
  const stack: [NodeId, FolderPath][] = ROOT_KEYS.flatMap((root) => {
    const id = tree.root_ids[root];
    return id === undefined ? [] : [[id, { root, names: [] }] as [NodeId, FolderPath]];
  });
  for (let next = stack.pop(); next !== undefined; next = stack.pop()) {
    const [id, path] = next;
    if (paths.has(id)) continue;
    paths.set(id, path);
    for (const child of children.get(id) ?? []) stack.push([child.id, { root: path.root, names: [...path.names, child.title] }]);
  }
  return paths;
}

function asCandidate(node: SnapshotNode, paths: ReadonlyMap<NodeId, FolderPath>, skip: readonly FolderPath[]): Bookmark | undefined {
  if (node.kind !== 'bookmark' || node.parent_id === null || !isCapturableUrl(node.url)) return undefined;
  const path = paths.get(node.parent_id);
  if (path === undefined || skip.some((folder) => isPathInside(path, folder))) return undefined;
  return { node_id: node.id, url: node.url, title: node.title, path, date_added: node.date_added };
}

/** Every bookmark a backfill ingests, in the order the tree read lists them. */
export function backfillCandidates(tree: TreeRead, skip: readonly FolderPath[]): NodeId[] {
  const paths = folderPaths(tree);
  return tree.nodes.flatMap((node) => (asCandidate(node, paths, skip) === undefined ? [] : [node.id]));
}

/** The candidate `node_id` as it is now, or undefined when it is gone or no longer a candidate. */
export function backfillBookmark(tree: TreeRead, node_id: NodeId, skip: readonly FolderPath[]): Bookmark | undefined {
  const node = tree.nodes.find((n) => n.id === node_id);
  return node === undefined ? undefined : asCandidate(node, folderPaths(tree), skip);
}

/** True when every candidate has been sent. */
export function isBackfillDone(progress: BackfillProgress): boolean {
  return progress.next_index >= progress.node_ids.length;
}
