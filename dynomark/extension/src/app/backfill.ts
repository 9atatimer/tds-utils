// backfill.ts -- the settings page's backfill (design, Open Question 3: run
// the existing tree through capture and indexing at first install --
// searchable, not re-filed -- and at what rate; contract v1, "Jobs": a
// backfill ingest is never offered a batch). The candidates are fixed when it
// starts and stored with the progress; each step sends one chunk of ingests
// (backfill true, no capture: the daemon fetches, and opening thousands of
// tabs is not a capture strategy), stores how far it got, and schedules the
// next chunk after a pause. A worker restart loses only the schedule: the next
// full hello resumes from the stored progress, and a repeated ingest is a
// no-op on the daemon.

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
import { CONTRACT_VERSION } from '../wire/messages.js';
import { DaemonError, isRetryable, resultOrThrow } from './errors.js';

// --- Constants ---

/** Ingests sent per step. */
export const BACKFILL_CHUNK = 10;
/** Quiet time between steps: at most BACKFILL_CHUNK ingests per BACKFILL_PAUSE_MS. */
export const BACKFILL_PAUSE_MS = 1000;

// --- Types ---

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

// --- Flow ---

/** Send one bookmark as a backfill ingest; a non-retryable refusal is reported and skipped, anything else stops the step. */
async function ingestBackfill(bookmark: Bookmark, deps: BackfillDeps, context: BackfillContext): Promise<void> {
  const fitted = fitBookmark(bookmark);
  if (fitted === undefined) return context.problem(`backfill: bookmark ${bookmark.node_id}: url over the contract's cap; not ingested`);
  try {
    resultOrThrow(
      await deps.transport.send({ v: CONTRACT_VERSION, type: 'ingest', id: deps.ids.next(), bookmark: fitted, backfill: true }),
    );
  } catch (error) {
    if (!(error instanceof DaemonError) || isRetryable(error.code)) throw error;
    context.problem(`backfill: ${bookmark.url}: ${error.message}`);
  }
}

// --- The backfill ---

export class Backfill {
  private running = false;

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
    let more = false;
    try {
      const progress = await this.deps.storage.loadBackfill();
      const skip = this.context.skip();
      if (progress === undefined || isBackfillDone(progress) || skip === undefined) return;
      const next = await this.sendChunk(progress, skip);
      await this.deps.storage.saveBackfill(next);
      more = !isBackfillDone(next);
    } finally {
      if (more) this.deps.timer.after(BACKFILL_PAUSE_MS, () => this.context.track(this.step()));
      else this.running = false;
    }
  }

  private async sendChunk(progress: BackfillProgress, skip: readonly FolderPath[]): Promise<BackfillProgress> {
    const chunk = progress.node_ids.slice(progress.next_index, progress.next_index + BACKFILL_CHUNK);
    const tree = await this.deps.tree.readTree();
    for (const node_id of chunk) {
      const bookmark = backfillBookmark(tree, node_id, skip);
      if (bookmark !== undefined) await ingestBackfill(bookmark, this.deps, this.context);
    }
    return { ...progress, next_index: progress.next_index + chunk.length };
  }
}
