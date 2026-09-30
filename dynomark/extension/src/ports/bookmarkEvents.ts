// bookmarkEvents.ts -- what the browser tells the extension about its tree
// (design, "The extension": Watch Follow Up on create or move; Record
// feedback on every move; tree.snapshot after changes under the owned roots).
// The browser adapter turns its own events into these values; the runtime
// decides what each means.

import type { SnapshotNode } from '../domain/tree.js';
import type { NodeId } from '../domain/values.js';

export type BookmarkEvent =
  | { readonly kind: 'created'; readonly node: SnapshotNode }
  | { readonly kind: 'moved'; readonly node_id: NodeId; readonly parent_id: NodeId; readonly old_parent_id: NodeId }
  | { readonly kind: 'changed'; readonly node_id: NodeId }
  | { readonly kind: 'removed'; readonly node_id: NodeId; readonly parent_id: NodeId }
  | { readonly kind: 'reordered'; readonly folder_id: NodeId };
