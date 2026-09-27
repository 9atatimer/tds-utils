// daemonEvents.ts -- the events the daemon pushes (contract v1 README,
// "Delivery and replay"; design, "Transport contract", delivery).
//
// job.updated and diff.proposed are acknowledged with events.ack, every
// copy, and their side effects are de-duplicated by event_id; of two copies
// of one job the higher seq is kept. A FILED or INDEXED job re-pulls the
// LocalIndex; an update during a pull does not restart it but makes one more
// pull follow. A batch.offer is the lane's: its receipt is its ack.
//
// An ack or receipt that cannot reach the daemon -- the link was lost, or the
// daemon (or dynomark-host with no daemon behind it) answered a retryable
// code -- is not a failure of the event: it stays unacknowledged on the
// daemon, which replays it after the next hello (design, "Transport
// contract": transport loss and daemon restart are retryable by
// reconnecting). Such an event resolves quietly and has no effect until then.

import type { TreeDiff } from '../domain/diff.js';
import { isNewerJob, refreshesIndex, type Job } from '../domain/jobs.js';
import type { WriteBatch } from '../domain/batch.js';
import type { EventId, Id, JobId } from '../domain/values.js';
import { TransportLost } from '../ports/transport.js';
import type { EventMessage } from '../wire/messages.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { DaemonError, isRetryable, resultOrThrow } from './errors.js';
import { syncIndex, type SyncDeps } from './syncIndex.js';

// --- Types ---

/** Where batch offers go (a BatchLane). */
export interface OfferSink {
  offer(batch: WriteBatch): Promise<void>;
}

// --- Predicates ---

/** True when the daemon's replay recovers from `error`: a lost link, or a retryable error code. */
function awaitsReplay(error: unknown): boolean {
  if (error instanceof TransportLost) return error.reason === 'disconnected';
  return error instanceof DaemonError && isRetryable(error.code);
}

/** `work`, with a failure the replay recovers from turned into a quiet resolution. */
async function unlessReplayed(work: Promise<void>): Promise<boolean> {
  try {
    await work;
    return true;
  } catch (error) {
    if (awaitsReplay(error)) return false;
    throw error;
  }
}

// --- Index refresh ---

/** Runs syncIndex; a request while a pull runs makes exactly one more pull follow it. */
class IndexRefresher {
  private running: Promise<void> | undefined;
  private again = false;
  readonly failures: unknown[] = [];

  constructor(private readonly deps: SyncDeps) {}

  request(): void {
    if (this.running !== undefined) {
      this.again = true;
      return;
    }
    this.running = this.loop();
  }

  idle(): Promise<void> {
    return this.running ?? Promise.resolve();
  }

  private async loop(): Promise<void> {
    do {
      this.again = false;
      try {
        await syncIndex(this.deps);
      } catch (error) {
        this.failures.push(error);
      }
    } while (this.again);
    this.running = undefined;
  }
}

// --- The handler ---

export class DaemonEvents {
  private readonly seen = new Set<EventId>();
  private readonly jobsById = new Map<JobId, Job>();
  private readonly diffsById = new Map<Id, TreeDiff>();
  private readonly refresher: IndexRefresher;

  constructor(
    private readonly deps: SyncDeps,
    private readonly lane: OfferSink,
  ) {
    this.refresher = new IndexRefresher(deps);
  }

  /** Handle one event frame; resolves once it is acknowledged (a batch.offer: once its receipt is), or once it is clear the daemon will replay it. */
  async handle(event: EventMessage): Promise<void> {
    if (event.type === 'batch.offer') {
      await unlessReplayed(this.lane.offer(event.batch));
      return;
    }
    if (!(await unlessReplayed(this.acknowledge(event.event_id)))) return;
    if (this.seen.has(event.event_id)) return;
    this.seen.add(event.event_id);
    if (event.type === 'job.updated') this.applyJob(event.job);
    else this.diffsById.set(event.diff.diff_id, event.diff);
  }

  /** The newest copy of each job seen on this worker. */
  jobs(): ReadonlyMap<JobId, Job> {
    return this.jobsById;
  }

  /** Each diff the daemon proposed on its own schedule, by id. */
  diffs(): ReadonlyMap<Id, TreeDiff> {
    return this.diffsById;
  }

  /** Resolves when no index pull is running or queued. */
  idle(): Promise<void> {
    return this.refresher.idle();
  }

  /** Index pulls that failed; the next FILED or INDEXED update (or full hello) pulls again. */
  failures(): readonly unknown[] {
    return this.refresher.failures;
  }

  private applyJob(job: Job): void {
    if (!isNewerJob(job, this.jobsById.get(job.job_id))) return;
    this.jobsById.set(job.job_id, job);
    if (refreshesIndex(job.state)) this.refresher.request();
  }

  private async acknowledge(event_id: EventId): Promise<void> {
    resultOrThrow(
      await this.deps.transport.send({ v: CONTRACT_VERSION, type: 'events.ack', id: this.deps.ids.next(), event_ids: [event_id] }),
    );
  }
}
