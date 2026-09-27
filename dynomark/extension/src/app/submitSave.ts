// submitSave.ts -- use case "A save is submitted" (design, Behaviors and
// Interfaces): submit_save(bookmark, capture, *, transport) -> RequestId.
//
// Ingest is idempotent on the node (contract v1, "Delivery and replay"), and
// a repeat of a request reuses its id and body. So one worker submits a node
// at most once: a second submission joins the first (in flight or answered),
// and a resubmission after a retryable error re-sends the identical frame.
// A busy or internal answer comes on a link that stays up, so no reconnect
// will re-send it (contract v1: busy and internal are retried with the same
// id after backoff): the identical frame is re-sent after a backoff, unless a
// resubmission comes first. A lost link is the reconnect backlog's.

import { backoffDelay } from '../domain/backoff.js';
import { fitBookmark } from '../domain/limits.js';
import { isExtensionCapture, type Capture } from '../domain/capture.js';
import type { Bookmark } from '../domain/tree.js';
import type { NodeId, RequestId, Url } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { Timer } from '../ports/timer.js';
import type { TransportPort } from '../ports/transport.js';
import type { MessageOf } from '../wire/messages.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { DaemonError, isRetryable, resultOrThrow } from './errors.js';

// --- Types ---

type IngestFrame = MessageOf<'ingest'>;

interface SaveEntry {
  readonly frame: IngestFrame;
  /** Set while the request is in flight or once it was answered `ingest.result`; cleared on an error answer. */
  outcome: Promise<RequestId> | undefined;
  /** Retryable answers so far: the backoff attempt of the next retry. */
  attempt: number;
  /** Cancels the retry waiting on its backoff, when one is. */
  cancelRetry: (() => void) | undefined;
}

export interface SaveDeps {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly saves: SubmittedSaves;
  readonly timer: Timer;
  /** Handed each retry this schedules (the caller reports its failure). */
  track(work: Promise<unknown>): void;
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

async function deliver(entry: SaveEntry, deps: SaveDeps): Promise<RequestId> {
  try {
    resultOrThrow(await deps.transport.send(entry.frame));
    return entry.frame.id;
  } catch (error) {
    entry.outcome = undefined;
    if (error instanceof DaemonError && isRetryable(error.code)) retryLater(entry, deps);
    throw error;
  }
}

/** Re-send the entry's frame, unchanged, after the next backoff. */
function retryLater(entry: SaveEntry, deps: SaveDeps): void {
  const delay = backoffDelay(entry.attempt);
  entry.attempt += 1;
  entry.cancelRetry = deps.timer.after(delay, () => {
    entry.cancelRetry = undefined;
    entry.outcome = deliver(entry, deps);
    deps.track(entry.outcome);
  });
}

/** Submit a Follow Up save to the daemon; resolves with its request id once the daemon has the job. */
export function submitSave(bookmark: Bookmark, capture: Capture, deps: SaveDeps): Promise<RequestId> {
  if (!isExtensionCapture(capture)) return Promise.reject(new TypeError("a fetch capture is the daemon's; the extension never sends one"));
  const fitted = fitBookmark(bookmark);
  if (fitted === undefined) return Promise.reject(new UrlTooLong(bookmark.node_id));
  const known = deps.saves.get(fitted.node_id, fitted.url);
  if (known?.outcome !== undefined) return known.outcome;
  const draft: IngestFrame = { v: CONTRACT_VERSION, type: 'ingest', id: '', bookmark: fitted, capture, backfill: false };
  const frame = known !== undefined && sameBody(known.frame, draft) ? known.frame : { ...draft, id: deps.ids.next() };
  known?.cancelRetry?.();
  const entry: SaveEntry = { frame, outcome: undefined, attempt: known?.attempt ?? 0, cancelRetry: undefined };
  entry.outcome = deliver(entry, deps);
  deps.saves.put(entry);
  return entry.outcome;
}
