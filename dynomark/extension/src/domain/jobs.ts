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
