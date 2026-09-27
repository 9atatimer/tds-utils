// submitSave.ts -- use case "A save is submitted" (design, Behaviors and
// Interfaces): submit_save(bookmark, capture, *, transport) -> RequestId.
//
// Ingest is idempotent on the node (contract v1, "Delivery and replay"), and
// a repeat of a request reuses its id and body. So one worker submits a node
// at most once: a second submission joins the first (in flight or answered),
// and a resubmission after a retryable error re-sends the identical frame.

import { fitBookmark } from '../domain/limits.js';
import { isExtensionCapture, type Capture } from '../domain/capture.js';
import type { Bookmark } from '../domain/tree.js';
import type { NodeId, RequestId, Url } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import type { MessageOf } from '../wire/messages.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';

// --- Types ---

type IngestFrame = MessageOf<'ingest'>;

interface SaveEntry {
  readonly frame: IngestFrame;
  /** Set while the request is in flight or once it was answered `ingest.result`; cleared on an error answer. */
  outcome: Promise<RequestId> | undefined;
}

/** A bookmark whose url is over the contract's cap is not ingested; the extension reports it locally. */
export class UrlTooLong extends Error {
  readonly node_id: NodeId;

  constructor(node_id: NodeId) {
    super(`bookmark ${node_id}: url over the contract's 65,536 code point cap; not ingested`);
    this.name = 'UrlTooLong';
    this.node_id = node_id;
  }
}

/** This worker's submissions, keyed by node and url (the daemon's idempotency key). In memory: not durable state. */
export class SubmittedSaves {
  private readonly entries = new Map<string, SaveEntry>();

  get(node_id: NodeId, url: Url): SaveEntry | undefined {
    return this.entries.get(saveKey(node_id, url));
  }

  put(entry: SaveEntry): void {
    this.entries.set(saveKey(entry.frame.bookmark.node_id, entry.frame.bookmark.url), entry);
  }
}

// --- Pure helpers ---

function saveKey(node_id: NodeId, url: Url): string {
  return `${node_id}\n${url}`;
}

function sameBody(a: IngestFrame, b: IngestFrame): boolean {
  return JSON.stringify({ ...a, id: '' }) === JSON.stringify({ ...b, id: '' });
}

// --- Flow ---

async function deliver(entry: SaveEntry, transport: TransportPort): Promise<RequestId> {
  try {
    resultOrThrow(await transport.send(entry.frame));
    return entry.frame.id;
  } catch (error) {
    entry.outcome = undefined;
    throw error;
  }
}

/** Submit a Follow Up save to the daemon; resolves with its request id once the daemon has the job. */
export function submitSave(
  bookmark: Bookmark,
  capture: Capture,
  deps: { readonly transport: TransportPort; readonly ids: IdSource; readonly saves: SubmittedSaves },
): Promise<RequestId> {
  if (!isExtensionCapture(capture)) return Promise.reject(new TypeError("a fetch capture is the daemon's; the extension never sends one"));
  const fitted = fitBookmark(bookmark);
  if (fitted === undefined) return Promise.reject(new UrlTooLong(bookmark.node_id));
  const known = deps.saves.get(fitted.node_id, fitted.url);
  if (known?.outcome !== undefined) return known.outcome;
  const draft: IngestFrame = { v: CONTRACT_VERSION, type: 'ingest', id: '', bookmark: fitted, capture, backfill: false };
  const frame = known !== undefined && sameBody(known.frame, draft) ? known.frame : { ...draft, id: deps.ids.next() };
  const entry: SaveEntry = { frame, outcome: undefined };
  entry.outcome = deliver(entry, deps.transport);
  deps.saves.put(entry);
  return entry.outcome;
}
