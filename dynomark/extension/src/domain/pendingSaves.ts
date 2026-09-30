// pendingSaves.ts -- the Follow Up saves sent and not yet answered
// ingest.result (contract v1, "Delivery and replay": busy and internal are
// retried with the same id and body). Kept so a worker that dies before the
// answer re-sends the identical request, captured text included, rather than
// a fresh one with no capture. Bounded: a few entries and at most one
// maximum capture's worth of text; the oldest go first, and a save that does
// not fit alone is not kept (it is sent all the same).

import type { ExtensionCapture } from './capture.js';
import { MAX_CAPTURE_TEXT } from './limits.js';
import type { Bookmark } from './tree.js';
import type { NodeId, RequestId, Url } from './values.js';

// --- Types ---

/** One ingest request as sent: its id, the bookmark and the capture it carried. */
export interface PendingSave {
  readonly id: RequestId;
  readonly bookmark: Bookmark;
  readonly capture: ExtensionCapture;
}

// --- Constants ---

/** At most this many saves are kept pending at once. */
export const MAX_PENDING_SAVES = 16;
/** At most this much capture text (UTF-16 code units) is kept across all pending saves. */
export const MAX_PENDING_TEXT = MAX_CAPTURE_TEXT;

// --- Pure helpers ---

function textOf(saves: readonly PendingSave[]): number {
  return saves.reduce((sum, save) => sum + save.capture.text.length, 0);
}

/** The pending save for this node and url (the daemon's idempotency key), if one is kept. */
export function pendingFor(saves: readonly PendingSave[], node_id: NodeId, url: Url): PendingSave | undefined {
  return saves.find((save) => save.bookmark.node_id === node_id && save.bookmark.url === url);
}

/** `saves` with `save` kept in place of any for its node and url, oldest dropped to fit; without it when it cannot fit alone. */
export function withPending(saves: readonly PendingSave[], save: PendingSave): PendingSave[] {
  const others = saves.filter((kept) => kept.bookmark.node_id !== save.bookmark.node_id || kept.bookmark.url !== save.bookmark.url);
  if (save.capture.text.length > MAX_PENDING_TEXT) return others;
  const next = [...others, save];
  while (next.length > MAX_PENDING_SAVES || textOf(next) > MAX_PENDING_TEXT) next.shift();
  return next;
}

/** `saves` without the request `id`. */
export function withoutPending(saves: readonly PendingSave[], id: RequestId): PendingSave[] {
  return saves.filter((save) => save.id !== id);
}
