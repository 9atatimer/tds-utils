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
//
// A frame is kept in storage from before it is first sent until it is answered
// ingest.result or refused for good, so a worker that dies in between (in
// flight, or waiting out a backoff) leaves it for the next: that worker's
// backlog adopts it and re-sends it unchanged, captured text included.

import { backoffDelay } from '../domain/backoff.js';
import { fitBookmark } from '../domain/limits.js';
import { isExtensionCapture, type Capture, type ExtensionCapture } from '../domain/capture.js';
import { pendingFor, withPending, withoutPending, type PendingSave } from '../domain/pendingSaves.js';
import type { Bookmark } from '../domain/tree.js';
import type { NodeId, RequestId, Url } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
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
  /** The daemon has this node's save: called on the `ingest.result` answer, whichever send of the frame (first or a retry) got it. */
  taken?(node_id: NodeId): Promise<void>;
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

/**
 * This worker's submissions, keyed by node and url (the daemon's idempotency
 * key), in memory; and the frames not yet answered, in storage (read once per
 * worker, then written through in call order).
 */
export class SubmittedSaves {
  private readonly entries = new Map<string, SaveEntry>();
  private pending: readonly PendingSave[] | undefined;
  private loading: Promise<readonly PendingSave[]> | undefined;

  constructor(private readonly storage: StoragePort) {}

  get(node_id: NodeId, url: Url): SaveEntry | undefined {
    return this.entries.get(saveKey(node_id, url));
  }

  put(entry: SaveEntry): void {
    this.entries.set(saveKey(entry.frame.bookmark.node_id, entry.frame.bookmark.url), entry);
  }

  /**
   * The capture of a frame sent for this node and url and not answered: this
   * worker's, or one an earlier worker left (adopted, so a submission re-sends
   * it unchanged).
   */
  async recall(node_id: NodeId, url: Url): Promise<ExtensionCapture | undefined> {
    const known = this.get(node_id, url)?.frame.capture;
    if (known !== undefined) return isExtensionCapture(known) ? known : undefined;
    await this.load();
    const kept = pendingFor(this.pending ?? [], node_id, url);
    if (kept === undefined) return undefined;
    this.put({ frame: frameOf(kept), outcome: undefined, attempt: 0, cancelRetry: undefined });
    return kept.capture;
  }

  /** Keep `frame` until it is answered. */
  async hold(frame: IngestFrame): Promise<void> {
    const save = pendingOf(frame);
    await this.load();
    const current = this.pending ?? [];
    if (save === undefined || pendingFor(current, save.bookmark.node_id, save.bookmark.url)?.id === save.id) return;
    await this.store(withPending(current, save));
  }

  /** Forget `frame`: it was answered, or refused for good. */
  async release(frame: IngestFrame): Promise<void> {
    await this.load();
    const current = this.pending ?? [];
    if (current.some((save) => save.id === frame.id)) await this.store(withoutPending(current, frame.id));
  }

  private async load(): Promise<void> {
    if (this.pending !== undefined) return;
    this.loading ??= this.storage.loadPendingSaves().then(
      (saves) => saves ?? [],
      (error: unknown) => {
        this.loading = undefined;
        throw error;
      },
    );
    const stored = await this.loading;
    this.pending ??= stored;
  }

  private store(saves: readonly PendingSave[]): Promise<void> {
    this.pending = saves;
    return this.storage.savePendingSaves(saves);
  }
}

// --- Pure helpers ---

function saveKey(node_id: NodeId, url: Url): string {
  return `${node_id}\n${url}`;
}

function frameOf(save: PendingSave): IngestFrame {
  return { v: CONTRACT_VERSION, type: 'ingest', id: save.id, bookmark: save.bookmark, capture: save.capture, backfill: false };
}

function pendingOf(frame: IngestFrame): PendingSave | undefined {
  const capture = frame.capture;
  if (capture === undefined || !isExtensionCapture(capture)) return undefined;
  return { id: frame.id, bookmark: frame.bookmark, capture };
}

function sameBody(a: IngestFrame, b: IngestFrame): boolean {
  return JSON.stringify({ ...a, id: '' }) === JSON.stringify({ ...b, id: '' });
}

// --- Flow ---

async function deliver(entry: SaveEntry, deps: SaveDeps): Promise<RequestId> {
  try {
    await deps.saves.hold(entry.frame);
    resultOrThrow(await deps.transport.send(entry.frame));
  } catch (error) {
    entry.outcome = undefined;
    if (error instanceof DaemonError && isRetryable(error.code)) retryLater(entry, deps);
    else if (error instanceof DaemonError) await deps.saves.release(entry.frame);
    throw error;
  }
  await deps.saves.release(entry.frame);
  await deps.taken?.(entry.frame.bookmark.node_id);
  return entry.frame.id;
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
