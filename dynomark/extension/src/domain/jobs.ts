// jobs.ts -- the daemon's durable unit of work, as the extension sees it
// (design, "Job" and "State Machine").

import type { CaptureSource } from './capture.js';
import type { BatchId, Identity, JobId, NodeId } from './values.js';

export type JobState = 'QUEUED' | 'CAPTURING' | 'ENRICHED' | 'PLACED' | 'FILED' | 'INDEXED' | 'FAILED';

export interface Job {
  readonly job_id: JobId;
  readonly node_id: NodeId;
  readonly identity: Identity;
  readonly state: JobState;
  /** Per-job sequence: of two copies of one job, the higher `seq` wins. */
  readonly seq: number;
  readonly attempts: number;
  readonly backfill: boolean;
  readonly capture_source?: CaptureSource;
  readonly last_error?: string;
  readonly batch_id?: BatchId;
}

// --- Predicates ---

/** True when `incoming` is newer than what is kept for its job: of two copies of one job, the higher seq wins. */
export function isNewerJob(incoming: Job, kept: Job | undefined): boolean {
  return kept === undefined || incoming.seq > kept.seq;
}

/** True when a job in this state changed the corpus the LocalIndex is built from (contract v1, Index freshness). */
export function refreshesIndex(state: JobState): boolean {
  return state === 'FILED' || state === 'INDEXED';
}
