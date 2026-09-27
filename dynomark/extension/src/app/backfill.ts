// backfill.ts -- the settings page's backfill (design, Open Question 3: run
// the existing tree through capture and indexing at first install --
// searchable, not re-filed -- and at what rate; contract v1, "Jobs": a
// backfill ingest is never offered a batch). The candidates are fixed when it
// starts and stored with the progress; each step sends one chunk of ingests
// (backfill true, no capture: the daemon fetches, and opening thousands of
// tabs is not a capture strategy), stores how far it got, and schedules the
// next chunk after a pause. A busy or internal answer comes on a link that
// stays up, so no reconnect will resume it (contract v1: busy and internal are
// retried with the same id after backoff): the step stores progress up to that
// bookmark and the next step, after a backoff, re-sends the identical frame.
// A worker restart loses only the schedule and the retained frame: the next
// full hello resumes from the stored progress, and a repeated ingest is a
// no-op on the daemon.

import { backoffDelay } from '../domain/backoff.js';
import { backfillBookmark, backfillCandidates, isBackfillDone, type BackfillProgress } from '../domain/backfill.js';
import { fitBookmark } from '../domain/limits.js';
import type { Bookmark, FolderPath } from '../domain/tree.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { Clock } from '../ports/clock.js';
import type { IdSource } from '../ports/idSource.js';
import type { StoragePort } from '../ports/storage.js';
import type { Timer } from '../ports/timer.js';
import type { BackfillView } from '../ports/pages.js';
import type { TransportPort } from '../ports/transport.js';
import type { MessageOf } from '../wire/messages.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { DaemonError, isRetryable, resultOrThrow } from './errors.js';

// --- Constants ---

/** Ingests sent per step. */
export const BACKFILL_CHUNK = 10;
/** Quiet time between steps: at most BACKFILL_CHUNK ingests per BACKFILL_PAUSE_MS. */
export const BACKFILL_PAUSE_MS = 1000;

// --- Types ---

type IngestFrame = MessageOf<'ingest'>;

/** A frame the daemon answered busy or internal: re-sent unchanged by the next step. In memory only. */
interface Retry {
  readonly frame: IngestFrame;
  /** Retryable answers so far: the backoff attempt of the next retry. */
  readonly attempt: number;
}

/** How far a step got: the progress to store, and the backoff to wait when it stopped on a retryable answer. */
interface Sent {
  readonly progress: BackfillProgress;
  readonly backoff: number | undefined;
}

export interface BackfillDeps {
  readonly tree: BookmarkTreePort;
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly storage: StoragePort;
  readonly timer: Timer;
  readonly clock: Clock;
}

export interface BackfillContext {
  /** The folders whose bookmarks are not backfilled (Follow Up, Graveyard); undefined while not connected in full mode. */
  skip(): readonly FolderPath[] | undefined;
  track(work: Promise<unknown>): void;
  problem(message: string): void;
}

// --- Pure helpers ---

function sameBody(a: IngestFrame, b: IngestFrame): boolean {
  return JSON.stringify({ ...a, id: '' }) === JSON.stringify({ ...b, id: '' });
}

// --- The backfill ---

export class Backfill {
  private running = false;
  private retry: Retry | undefined;

  constructor(
    private readonly deps: BackfillDeps,
    private readonly context: BackfillContext,
  ) {}

  /** Start a backfill of the tree as it is now; a running or unfinished one is continued instead of restarted. */
  async start(): Promise<BackfillView> {
    const skip = this.context.skip();
    if (skip === undefined) throw new Error('backfill needs a full connection to the daemon');
    const stored = await this.deps.storage.loadBackfill();
    if (stored === undefined || isBackfillDone(stored)) {
      const node_ids = backfillCandidates(await this.deps.tree.readTree(), skip);
      await this.deps.storage.saveBackfill({ started_at: this.deps.clock.now(), node_ids, next_index: 0 });
    }
    this.resume();
    return (await this.view()) ?? { total: 0, done: 0, running: this.running };
  }

  /** Continue a stored, unfinished backfill (after a full hello). */
  resume(): void {
    if (this.running) return;
    this.running = true;
    this.context.track(this.step());
  }

  /** Progress for the settings page; undefined when no backfill was ever started. */
  async view(): Promise<BackfillView | undefined> {
    const progress = await this.deps.storage.loadBackfill();
    if (progress === undefined) return undefined;
    return { total: progress.node_ids.length, done: Math.min(progress.next_index, progress.node_ids.length), running: this.running };
  }

  private async step(): Promise<void> {
    let delay: number | undefined;
    try {
      const progress = await this.deps.storage.loadBackfill();
      const skip = this.context.skip();
      if (progress === undefined || isBackfillDone(progress) || skip === undefined) return;
      const sent = await this.sendChunk(progress, skip);
      await this.deps.storage.saveBackfill(sent.progress);
      delay = sent.backoff ?? (isBackfillDone(sent.progress) ? undefined : BACKFILL_PAUSE_MS);
    } finally {
      if (delay !== undefined) this.deps.timer.after(delay, () => this.context.track(this.step()));
      else this.running = false;
    }
  }

  private async sendChunk(progress: BackfillProgress, skip: readonly FolderPath[]): Promise<Sent> {
    const chunk = progress.node_ids.slice(progress.next_index, progress.next_index + BACKFILL_CHUNK);
    const tree = await this.deps.tree.readTree();
    for (const [offset, node_id] of chunk.entries()) {
      const bookmark = backfillBookmark(tree, node_id, skip);
      const backoff = bookmark === undefined ? undefined : await this.ingest(bookmark);
      if (backoff !== undefined) return { progress: { ...progress, next_index: progress.next_index + offset }, backoff };
    }
    return { progress: { ...progress, next_index: progress.next_index + chunk.length }, backoff: undefined };
  }

  /**
   * Send one bookmark as a backfill ingest (the retained frame, when this is
   * the one last answered busy or internal). A non-retryable refusal is
   * reported and skipped; a retryable one is retained and its backoff returned;
   * anything else stops the step.
   */
  private async ingest(bookmark: Bookmark): Promise<number | undefined> {
    const fitted = fitBookmark(bookmark);
    if (fitted === undefined) {
      this.context.problem(`backfill: bookmark ${bookmark.node_id}: url over the contract's cap; not ingested`);
      return undefined;
    }
    const draft: IngestFrame = { v: CONTRACT_VERSION, type: 'ingest', id: '', bookmark: fitted, backfill: true };
    const retry = this.retry !== undefined && sameBody(this.retry.frame, draft) ? this.retry : undefined;
    const frame = retry?.frame ?? { ...draft, id: this.deps.ids.next() };
    this.retry = undefined;
    try {
      resultOrThrow(await this.deps.transport.send(frame));
    } catch (error) {
      if (!(error instanceof DaemonError)) throw error;
      if (!isRetryable(error.code)) {
        this.context.problem(`backfill: ${bookmark.url}: ${error.message}`);
        return undefined;
      }
      const attempt = retry?.attempt ?? 0;
      this.retry = { frame, attempt: attempt + 1 };
      return backoffDelay(attempt);
    }
    return undefined;
  }
}
