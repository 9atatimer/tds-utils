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
import type { WriterStatus } from '../domain/writer.js';
import type { DiffItem, DiffKind, OutlineFolder, PlacementReason, TreeDiff, UndoDrop } from '../domain/diff.js';
import type { Answer, Question, Turn } from '../domain/chat.js';
import type { EpochMs, Id, Identity, NodeId, Title, Url } from '../domain/values.js';

// --- Requests ---

export type PageRequest =
  | { readonly kind: 'overview' }
  | { readonly kind: 'settings.set'; readonly capture_from_tab: boolean }
  | { readonly kind: 'batch.list'; readonly cursor?: Cursor }
  | { readonly kind: 'undo'; readonly batch_id: BatchId }
  | { readonly kind: 'job.list'; readonly cursor?: Cursor }
  | { readonly kind: 'job.retry'; readonly job_id: JobId }
  | { readonly kind: 'ask'; readonly question: Question; readonly history: readonly Turn[] }
  | { readonly kind: 'explain'; readonly identity: Identity }
  | { readonly kind: 'open'; readonly url: Url }
  | { readonly kind: 'file'; readonly url: Url; readonly title: Title }
  | { readonly kind: 'diff.list'; readonly cursor?: Cursor }
  | { readonly kind: 'diff.page'; readonly diff_id: Id; readonly cursor?: Cursor }
  | { readonly kind: 'diff.propose'; readonly diff_kind: DiffKind }
  | { readonly kind: 'diff.accept'; readonly item_id: Id }
  | { readonly kind: 'outline'; readonly cursor?: Cursor }
  | {
      readonly kind: 'folder.flags';
      readonly node_id: NodeId;
      readonly path: FolderPath;
      readonly pinned?: boolean;
      readonly locked?: boolean;
    };

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
  /** The writer marker as the daemon last reported it; `conflict` is shown prominently. */
  readonly writer?: WriterStatus;
  readonly writer_error?: string;
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
  | { readonly ok: true; readonly kind: 'ask'; readonly answer: Answer }
  | { readonly ok: true; readonly kind: 'explain'; readonly reason: PlacementReason }
  | { readonly ok: true; readonly kind: 'open' }
  | { readonly ok: true; readonly kind: 'file'; readonly node_id: NodeId; readonly created: boolean }
  | { readonly ok: true; readonly kind: 'diff.list'; readonly diffs: readonly TreeDiff[]; readonly next_cursor: Cursor | null }
  | {
      readonly ok: true;
      readonly kind: 'diff.page';
      readonly diff: TreeDiff;
      readonly items: readonly DiffItem[];
      readonly next_cursor: Cursor | null;
    }
  | { readonly ok: true; readonly kind: 'diff.propose'; readonly diff: TreeDiff }
  | { readonly ok: true; readonly kind: 'diff.accept'; readonly item_id: Id; readonly accepted_at: EpochMs; readonly batch_id: BatchId }
  | { readonly ok: true; readonly kind: 'outline'; readonly folders: readonly OutlineFolder[]; readonly next_cursor: Cursor | null }
  | { readonly ok: true; readonly kind: 'folder.flags'; readonly folder: OutlineFolder }
  | { readonly ok: false; readonly error: string; readonly code?: ErrorCode };

/** How a page asks the background. */
export interface PageClient {
  request(request: PageRequest): Promise<PageResponse>;
}
