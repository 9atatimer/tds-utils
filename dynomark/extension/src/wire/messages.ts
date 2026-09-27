// messages.ts -- zod schemas for every contract v1 message, one discriminated
// union on `type`, split by direction (contract v1 README, "Envelope"):
// requests carry `id` (extension -> daemon), responses carry `re` and events
// carry `event_id` (daemon -> extension). Every object is strict.

import { z } from 'zod';
import {
  AnswerSchema,
  BatchReceiptSchema,
  BatchSummarySchema,
  BookmarkSchema,
  CaptureSchema,
  CursorSchema,
  DetailSchema,
  DiffItemSchema,
  DiffKindSchema,
  ErrorCodeSchema,
  FolderPathSchema,
  HelloModeSchema,
  HitSchema,
  HostIdSchema,
  HostRoleSchema,
  IdSchema,
  IdentitySchema,
  JobSchema,
  JobStateSchema,
  LocalIndexRowSchema,
  ModelInfoSchema,
  MoveSchema,
  NodeIdSchema,
  OutlineFolderSchema,
  OwnedRootsSchema,
  PlacementReasonSchema,
  SnapshotSchema,
  TreeDiffSchema,
  TurnSchema,
  UndoDropSchema,
  UrlSchema,
  WriteBatchSchema,
  count,
  text,
  uniqueArray,
} from './values.js';

// --- Constants ---

/** The contract version this build speaks (contract/v1/CONTRACT_VERSION). */
export const CONTRACT_VERSION = 1;

/** Non-frozen messages pin `v` to this build's version. */
const V = z.literal(CONTRACT_VERSION);
/** The frozen messages (hello, hello.result, error) accept any version, so any two versions can shake hands. */
const V_FROZEN = z.int().min(1);

const nextCursor = CursorSchema.nullable();
const pageLimit = (max: number) => z.int().min(1).max(max).exactOptional();

// --- Envelope helpers ---

function request<T extends string, S extends z.core.$ZodLooseShape>(type: T, shape: S) {
  return z.strictObject({ v: V, type: z.literal(type), id: IdSchema, ...shape });
}

function response<T extends string, S extends z.core.$ZodLooseShape>(type: T, shape: S) {
  return z.strictObject({ v: V, type: z.literal(type), re: IdSchema, ...shape });
}

function event<T extends string, S extends z.core.$ZodLooseShape>(type: T, shape: S) {
  return z.strictObject({ v: V, type: z.literal(type), event_id: IdSchema, ...shape });
}

// --- Requests (extension -> daemon) ---

export const HelloSchema = z.strictObject({
  v: V_FROZEN,
  type: z.literal('hello'),
  id: IdSchema,
  profile_id: IdSchema,
  follow_up: FolderPathSchema,
});
export const IngestSchema = request('ingest', { bookmark: BookmarkSchema, capture: CaptureSchema.exactOptional(), backfill: z.boolean() });
export const JobRetrySchema = request('job.retry', { job_id: IdSchema });
export const JobListSchema = request('job.list', {
  state: JobStateSchema.exactOptional(),
  cursor: CursorSchema.exactOptional(),
  limit: pageLimit(1000),
});
export const TreeSnapshotSchema = request('tree.snapshot', { snapshot: SnapshotSchema });
export const MoveObservedSchema = request('move.observed', { move: MoveSchema });
export const BatchReceiptMessageSchema = request('batch.receipt', { receipt: BatchReceiptSchema });
export const EventsReplaySchema = request('events.replay', {});
export const EventsAckSchema = request('events.ack', { event_ids: z.array(IdSchema).min(1).max(1000) });
export const IndexPullSchema = request('index.pull', { cursor: CursorSchema.exactOptional(), limit: pageLimit(1000) });
export const SearchSchema = request('search', {
  query: text({ min: 1, max: 1024 }),
  cursor: CursorSchema.exactOptional(),
  limit: pageLimit(100),
});
export const AskSchema = request('ask', { question: text({ min: 1, max: 8192 }), history: z.array(TurnSchema).max(50) });
export const PlacementExplainSchema = request('placement.explain', {
  identity: IdentitySchema.exactOptional(),
  url: UrlSchema.exactOptional(),
}).refine((m) => (m.identity === undefined) !== (m.url === undefined), { message: 'placement.explain takes identity xor url' });
export const UndoSchema = request('undo', { batch_id: IdSchema });
export const BatchListSchema = request('batch.list', { cursor: CursorSchema.exactOptional(), limit: pageLimit(100) });
export const DiffProposeSchema = request('diff.propose', { kind: DiffKindSchema });
export const DiffListSchema = request('diff.list', { cursor: CursorSchema.exactOptional(), limit: pageLimit(100) });
export const DiffPageSchema = request('diff.page', { diff_id: IdSchema, cursor: CursorSchema.exactOptional(), limit: pageLimit(100) });
export const DiffAcceptSchema = request('diff.accept', { item_id: IdSchema });
export const OutlineGetSchema = request('outline.get', { cursor: CursorSchema.exactOptional(), limit: pageLimit(1000) });
export const FolderFlagsSetSchema = request('folder.flags.set', {
  node_id: NodeIdSchema,
  path: FolderPathSchema.exactOptional(),
  pinned: z.boolean().exactOptional(),
  locked: z.boolean().exactOptional(),
}).refine((m) => m.pinned !== undefined || m.locked !== undefined, { message: 'folder.flags.set changes at least one flag' });
export const WriterStatusSchema = request('writer.status', {});
export const StatusSchema = request('status', {});

// --- Responses (daemon -> extension) ---

export const HelloResultSchema = z.strictObject({
  v: V_FROZEN,
  type: z.literal('hello.result'),
  re: IdSchema,
  host_id: HostIdSchema,
  role: HostRoleSchema,
  mode: HelloModeSchema,
  owned_roots: OwnedRootsSchema,
});
export const IngestResultSchema = response('ingest.result', { job: JobSchema });
export const JobRetryResultSchema = response('job.retry.result', { job: JobSchema });
export const JobListResultSchema = response('job.list.result', { jobs: z.array(JobSchema).max(1000), next_cursor: nextCursor });
export const TreeSnapshotResultSchema = response('tree.snapshot.result', {});
export const MoveObservedResultSchema = response('move.observed.result', {});
export const BatchReceiptMessageResultSchema = response('batch.receipt.result', {});
export const EventsReplayResultSchema = response('events.replay.result', { count: count() });
export const EventsAckResultSchema = response('events.ack.result', {});
export const IndexPullResultSchema = response('index.pull.result', {
  rows: z.array(LocalIndexRowSchema).max(1000),
  next_cursor: nextCursor,
});
export const SearchResultSchema = response('search.result', {
  hits: z.array(HitSchema.extend({ tier: z.literal('corpus') })).max(100),
  next_cursor: nextCursor,
});
export const AskResultSchema = response('ask.result', { answer: AnswerSchema });
export const PlacementExplainResultSchema = response('placement.explain.result', { reason: PlacementReasonSchema });
export const UndoResultSchema = response('undo.result', {
  batch_id: IdSchema.nullable(),
  undoes: IdSchema,
  dropped: z.array(UndoDropSchema).max(1000),
});
export const BatchListResultSchema = response('batch.list.result', {
  batches: z.array(BatchSummarySchema).max(100),
  next_cursor: nextCursor,
});
export const DiffProposeResultSchema = response('diff.propose.result', { diff: TreeDiffSchema });
export const DiffListResultSchema = response('diff.list.result', { diffs: z.array(TreeDiffSchema).max(100), next_cursor: nextCursor });
export const DiffPageResultSchema = response('diff.page.result', {
  diff: TreeDiffSchema,
  items: z.array(DiffItemSchema).max(100),
  next_cursor: nextCursor,
});
export const DiffAcceptResultSchema = response('diff.accept.result', { item_id: IdSchema, accepted_at: count(), batch_id: IdSchema });
export const OutlineGetResultSchema = response('outline.get.result', {
  outline: z.array(OutlineFolderSchema).max(1000),
  next_cursor: nextCursor,
});
export const FolderFlagsSetResultSchema = response('folder.flags.set.result', { folder: OutlineFolderSchema });
export const WriterStatusResultSchema = response('writer.status.result', {
  role: HostRoleSchema,
  host_id: HostIdSchema,
  own_marker: z.boolean(),
  other_writers: uniqueArray(HostIdSchema, { max: 64 }),
  conflict: z.boolean(),
});
export const StatusResultSchema = response('status.result', {
  role: HostRoleSchema,
  host_id: HostIdSchema,
  contract_version: z.int().min(1),
  models: z.strictObject({ embedding: ModelInfoSchema, completion: ModelInfoSchema }),
  queue_depth: count(),
});
/** The one error response. `re` is null when the request id was unreadable, and for `superseded`. */
export const ErrorSchema = z.strictObject({
  v: V_FROZEN,
  type: z.literal('error'),
  re: IdSchema.nullable(),
  code: ErrorCodeSchema,
  message: DetailSchema,
});

// --- Events (daemon -> extension) ---

export const JobUpdatedSchema = event('job.updated', { job: JobSchema });
export const BatchOfferSchema = event('batch.offer', { batch: WriteBatchSchema });
export const DiffProposedSchema = event('diff.proposed', { diff: TreeDiffSchema });

// --- Unions ---

const REQUESTS = [
  HelloSchema,
  IngestSchema,
  JobRetrySchema,
  JobListSchema,
  TreeSnapshotSchema,
  MoveObservedSchema,
  BatchReceiptMessageSchema,
  EventsReplaySchema,
  EventsAckSchema,
  IndexPullSchema,
  SearchSchema,
  AskSchema,
  PlacementExplainSchema,
  UndoSchema,
  BatchListSchema,
  DiffProposeSchema,
  DiffListSchema,
  DiffPageSchema,
  DiffAcceptSchema,
  OutlineGetSchema,
  FolderFlagsSetSchema,
  WriterStatusSchema,
  StatusSchema,
] as const;

const RESPONSES = [
  HelloResultSchema,
  IngestResultSchema,
  JobRetryResultSchema,
  JobListResultSchema,
  TreeSnapshotResultSchema,
  MoveObservedResultSchema,
  BatchReceiptMessageResultSchema,
  EventsReplayResultSchema,
  EventsAckResultSchema,
  IndexPullResultSchema,
  SearchResultSchema,
  AskResultSchema,
  PlacementExplainResultSchema,
  UndoResultSchema,
  BatchListResultSchema,
  DiffProposeResultSchema,
  DiffListResultSchema,
  DiffPageResultSchema,
  DiffAcceptResultSchema,
  OutlineGetResultSchema,
  FolderFlagsSetResultSchema,
  WriterStatusResultSchema,
  StatusResultSchema,
  ErrorSchema,
] as const;

const EVENTS = [JobUpdatedSchema, BatchOfferSchema, DiffProposedSchema] as const;

export const RequestSchema = z.discriminatedUnion('type', REQUESTS);
export const ResponseSchema = z.discriminatedUnion('type', RESPONSES);
export const EventSchema = z.discriminatedUnion('type', EVENTS);
/** Every frame on either hop is exactly one of these. */
export const MessageSchema = z.discriminatedUnion('type', [...REQUESTS, ...RESPONSES, ...EVENTS]);

// --- Types ---

export type Message = z.output<typeof MessageSchema>;
export type RequestMessage = z.output<typeof RequestSchema>;
export type ResponseMessage = z.output<typeof ResponseSchema>;
export type EventMessage = z.output<typeof EventSchema>;
export type ErrorMessage = z.output<typeof ErrorSchema>;
export type MessageType = Message['type'];
export type RequestType = RequestMessage['type'];
/** The message of one type. */
export type MessageOf<T extends MessageType> = Extract<Message, { readonly type: T }>;
/** The response a request of type T is answered with on success: `T.result`. */
export type ResultOf<T extends RequestType> = MessageOf<`${T}.result` & MessageType>;
