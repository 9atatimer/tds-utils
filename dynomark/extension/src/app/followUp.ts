// followUp.ts -- open the Follow Up folder the extension watches (design,
// "The extension", Watch Follow Up): the domain rule decides which folder, or
// where to create one; this runs it against the tree.

import { resolveFollowUp } from '../domain/followUp.js';
import { resolveFolderPath } from '../domain/paths.js';
import type { FolderPath } from '../domain/tree.js';
import type { NodeId } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';

// --- Types ---

/** The watched folder, and every other folder of that title (to report). */
export interface FollowUpFolder {
  readonly node_id: NodeId;
  readonly path: FolderPath;
  readonly others: readonly NodeId[];
}

// --- Flow ---

/** The Follow Up folder, created directly under the bookmarks bar when there is none. */
export async function openFollowUp(deps: { readonly tree: BookmarkTreePort }): Promise<FollowUpFolder> {
  const read = await deps.tree.readTree();
  const resolution = resolveFollowUp(read);
  if (resolution.kind === 'use') return { node_id: resolution.node_id, path: resolution.path, others: resolution.others };
  const parent = resolveFolderPath(read, resolution.parent);
  if (parent === undefined) throw new Error('the bookmarks bar does not resolve; cannot create Follow Up');
  const made = await deps.tree.createFolder(parent, resolution.title);
  return { node_id: made.id, path: { root: resolution.parent.root, names: [...resolution.parent.names, resolution.title] }, others: [] };
}
