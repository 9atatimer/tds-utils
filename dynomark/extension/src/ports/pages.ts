// pages.ts -- what an extension page asks the background for, and the answer
// (design, "The extension": Settings; "Chat surface ... is a view, not a
// composition root" -- so are the options and history pages). The pages
// speak this over the browser's runtime messaging; the background answers
// from the daemon through its one Connection.

import type { FolderPath } from '../domain/tree.js';
import type { BatchId, Cursor, JobId } from '../domain/values.js';
import type { ErrorCode } from '../wire/values.js';
import type { ResultOf } from '../wire/messages.js';
import type { LinkState } from './transport.js';
import type { ConnectionMode, HostRole } from '../domain/roles.js';
import type { Job } from '../domain/jobs.js';
import type { UndoDrop } from '../domain/diff.js';

// --- Requests ---

export type PageRequest =
  | { readonly kind: 'overview' }
  | { readonly kind: 'settings.set'; readonly capture_from_tab: boolean }
  | { readonly kind: 'batch.list'; readonly cursor?: Cursor }
  | { readonly kind: 'undo'; readonly batch_id: BatchId }
  | { readonly kind: 'job.list'; readonly cursor?: Cursor }
  | { readonly kind: 'job.retry'; readonly job_id: JobId };

// --- Answers ---

type StatusResult = ResultOf<'status'>;

/** Everything the options page shows. */
export interface Overview {
  readonly link: LinkState;
  /** What the current hello decided; absent while not connected. */
  readonly connection?: { readonly v: number; readonly mode: ConnectionMode; readonly role: HostRole; readonly host_id: string };
  /** The daemon's own status (role, host id, models, queue depth); absent when it could not be asked. */
  readonly daemon?: Pick<StatusResult, 'role' | 'host_id' | 'contract_version' | 'models' | 'queue_depth'>;
  readonly daemon_error?: string;
  readonly settings: { readonly profile_id: string; readonly capture_from_tab: boolean };
  readonly follow_up?: FolderPath;
  /** Things the user should know (extra Follow Up folders, failed background work), newest last. */
  readonly problems: readonly string[];
}

export type PageResponse =
  | { readonly ok: true; readonly kind: 'overview'; readonly overview: Overview }
  | { readonly ok: true; readonly kind: 'settings.set'; readonly capture_from_tab: boolean }
  | {
      readonly ok: true;
      readonly kind: 'batch.list';
      readonly batches: ResultOf<'batch.list'>['batches'];
      readonly next_cursor: Cursor | null;
    }
  | { readonly ok: true; readonly kind: 'undo'; readonly batch_id: BatchId | null; readonly dropped: readonly UndoDrop[] }
  | { readonly ok: true; readonly kind: 'job.list'; readonly jobs: readonly Job[]; readonly next_cursor: Cursor | null }
  | { readonly ok: true; readonly kind: 'job.retry'; readonly job: Job }
  | { readonly ok: false; readonly error: string; readonly code?: ErrorCode };
