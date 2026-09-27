// values.ts -- zod schemas for contract v1's shared values ($defs that are not
// messages). Each schema that has a domain counterpart is checked against it
// at compile time (`satisfies z.ZodType<DomainType>`), so a parsed wire value
// is a domain value with no mapping layer.

import { z } from 'zod';
import type { BatchReceipt, Operation, WriteBatch } from '../domain/batch.js';
import type { Capture } from '../domain/capture.js';
import type { Answer, EntryRef, Turn } from '../domain/chat.js';
import type { DiffItem, OutlineFolder, PlacementReason, TreeDiff, UndoDrop } from '../domain/diff.js';
import type { Job } from '../domain/jobs.js';
import type { Move } from '../domain/move.js';
import type { Hit, LocalIndexRow } from '../domain/search.js';
import type { Bookmark, FolderPath, OwnedRoots, RootIds, Snapshot, SnapshotNode } from '../domain/tree.js';
import { isWellFormed } from '../domain/text.js';
import { ROOT_KEYS } from '../domain/tree.js';

// --- Constants (contract v1 README, "Size limits") ---

const MAX_EPOCH_MS = Number.MAX_SAFE_INTEGER;
const MAX_TITLE = 4096;
const MAX_URL = 65536;
const MAX_DETAIL = 4096;
const MAX_CAPTURE_TEXT = 1_048_576;
const MAX_OP_INDEX = 999;
const MAX_OPS_PER_BATCH = 1000;
const MAX_OPS_PER_DIFF_ITEM = 100;

// --- Helpers ---

/**
 * A well-formed string whose length in code points lies in [min, max]. zod 4 counts code
 * points for string min/max (not UTF-16 units), as the contract requires;
 * test/unit/wire/code-points.test.ts pins that.
 */
export function text(bounds: { readonly min?: number; readonly max: number }): z.ZodString {
  return z
    .string()
    .min(bounds.min ?? 0)
    .max(bounds.max)
    .refine(isWellFormed, { message: 'a wire string holds no lone surrogate' });
}

/** A non-negative integer no larger than `max`. */
export function count(max = MAX_EPOCH_MS): z.ZodInt {
  return z.int().min(0).max(max);
}

/** An array whose items are pairwise distinct; a duplicate is reported at its own index. */
export function uniqueArray<T extends z.ZodType>(item: T, bounds: { readonly max: number }) {
  return z
    .array(item)
    .max(bounds.max)
    .superRefine((items, ctx) => {
      const seen = new Set<unknown>();
      items.forEach((value, index) => {
        if (seen.has(value)) ctx.addIssue({ code: 'custom', path: [index], message: 'items must be unique' });
        seen.add(value);
      });
    });
}

// --- Scalars ---

export const IdSchema = z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/);
export const NodeIdSchema = z.string().regex(/^[A-Za-z0-9._-]{1,64}$/);
export const HostIdSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/);
export const CursorSchema = z.string().regex(/^[!-~]{1,1024}$/);
export const EpochMsSchema = count();
export const UrlSchema = text({ min: 1, max: MAX_URL });
export const IdentitySchema = text({ min: 1, max: MAX_URL });
export const TitleSchema = text({ max: MAX_TITLE });
export const TagSchema = text({ min: 1, max: 64 });
export const DetailSchema = text({ max: MAX_DETAIL });
const OpIndexSchema = count(MAX_OP_INDEX);

// --- Enums ---

export const RootKeySchema = z.enum(ROOT_KEYS);
export const HostRoleSchema = z.enum(['writer', 'reader']);
export const CaptureSourceSchema = z.enum(['tab', 'background_tab', 'fetch', 'none']);
export const JobStateSchema = z.enum(['QUEUED', 'CAPTURING', 'ENRICHED', 'PLACED', 'FILED', 'INDEXED', 'FAILED']);
export const DiffKindSchema = z.enum(['audit', 'rebuild']);
export const MoveOriginSchema = z.enum(['user', 'extension']);
export const HitTierSchema = z.enum(['local', 'corpus']);
export const HelloModeSchema = z.enum(['full', 'read_only', 'refused']);
export const ErrorCodeSchema = z.enum([
  'version_mismatch',
  'hello_required',
  'not_writer',
  'writer_conflict',
  'not_found',
  'invalid',
  'stale_cursor',
  'busy',
  'internal',
  'superseded',
]);
export const BatchStateSchema = z.enum(['PROPOSED', 'APPLIED', 'PARTIAL', 'REJECTED']);
export const SkipReasonSchema = z.enum(['node_missing', 'parent_mismatch', 'not_empty']);
export const FailReasonSchema = z.enum(['parent_missing', 'browser_error']);
export const RejectReasonSchema = z.enum(['boundary', 'invalid', 'writer_conflict']);
export const UndoDropReasonSchema = z.enum(['node_moved', 'node_missing', 'not_empty']);
export const DiffActionSchema = z.enum(['add', 'move', 'merge']);

// --- Tree ---

export const FolderPathSchema = z.strictObject({
  root: RootKeySchema,
  names: z.array(TitleSchema).max(64),
}) satisfies z.ZodType<FolderPath>;

export const OwnedRootsSchema = z.strictObject({
  follow_up: FolderPathSchema,
  dynomark: FolderPathSchema,
  graveyard: FolderPathSchema,
}) satisfies z.ZodType<OwnedRoots>;

export const BookmarkSchema = z.strictObject({
  node_id: NodeIdSchema,
  url: UrlSchema,
  title: TitleSchema,
  path: FolderPathSchema,
  date_added: EpochMsSchema,
}) satisfies z.ZodType<Bookmark>;

const snapshotNodeBase = {
  id: NodeIdSchema,
  parent_id: NodeIdSchema.nullable(),
  index: count(),
  title: TitleSchema,
  truncated: z.literal(true).exactOptional(),
  date_added: EpochMsSchema,
};

export const SnapshotNodeSchema = z.discriminatedUnion('kind', [
  z.strictObject({ ...snapshotNodeBase, kind: z.literal('folder') }),
  z.strictObject({ ...snapshotNodeBase, kind: z.literal('bookmark'), url: UrlSchema }),
  z.strictObject({ ...snapshotNodeBase, kind: z.literal('separator') }),
]) satisfies z.ZodType<SnapshotNode>;

export const RootIdsSchema = z.strictObject({
  bar: NodeIdSchema,
  other: NodeIdSchema,
  mobile: NodeIdSchema.exactOptional(),
  menu: NodeIdSchema.exactOptional(),
}) satisfies z.ZodType<RootIds>;

export const SnapshotSchema = z.strictObject({
  taken_at: EpochMsSchema,
  root_ids: RootIdsSchema,
  nodes: z.array(SnapshotNodeSchema).min(1).max(500_000),
}) satisfies z.ZodType<Snapshot>;

// --- Capture ---

/** The extension never sends `fetch`; `none` carries empty text. */
export const CaptureSchema = z
  .strictObject({
    source: z.enum(['tab', 'background_tab', 'none']),
    text: text({ max: MAX_CAPTURE_TEXT }),
    title: TitleSchema.exactOptional(),
  })
  .refine((c) => c.source !== 'none' || c.text === '', {
    path: ['text'],
    message: 'source none carries empty text',
  }) satisfies z.ZodType<Capture>;

// --- Jobs ---

export const JobSchema = z.strictObject({
  job_id: IdSchema,
  node_id: NodeIdSchema,
  identity: IdentitySchema,
  state: JobStateSchema,
  seq: z.int().min(1).max(MAX_EPOCH_MS),
  attempts: count(),
  backfill: z.boolean(),
  capture_source: CaptureSourceSchema.exactOptional(),
  last_error: DetailSchema.exactOptional(),
  batch_id: IdSchema.exactOptional(),
}) satisfies z.ZodType<Job>;

// --- Operations and batches ---

const ExpectSchema = z.strictObject({
  parent_path: FolderPathSchema.exactOptional(),
  parent_id: NodeIdSchema,
  empty: z.literal(true).exactOptional(),
});

export const OperationSchema = z.discriminatedUnion('op', [
  z.strictObject({ op: z.literal('create_folder'), index: OpIndexSchema, parent: FolderPathSchema, title: TitleSchema }),
  z.strictObject({ op: z.literal('create'), index: OpIndexSchema, parent: FolderPathSchema, title: TitleSchema, url: UrlSchema }),
  z.strictObject({ op: z.literal('move'), index: OpIndexSchema, node_id: NodeIdSchema, to: FolderPathSchema, expect: ExpectSchema }),
  z.strictObject({ op: z.literal('remove'), index: OpIndexSchema, node_id: NodeIdSchema, expect: ExpectSchema }),
]) satisfies z.ZodType<Operation>;

export const WriteBatchSchema = z.strictObject({
  batch_id: IdSchema,
  operations: z.array(OperationSchema).min(1).max(MAX_OPS_PER_BATCH),
  diff_item_id: IdSchema.exactOptional(),
}) satisfies z.ZodType<WriteBatch>;

const OpAppliedSchema = z.strictObject({ index: OpIndexSchema, node_id: NodeIdSchema, changed: z.boolean() });
const OpSkippedSchema = z.strictObject({ index: OpIndexSchema, reason: SkipReasonSchema });
const OpFailedSchema = z.strictObject({ index: OpIndexSchema, reason: FailReasonSchema, detail: DetailSchema.exactOptional() });

const receiptBase = {
  batch_id: IdSchema,
  snapshot: SnapshotSchema.exactOptional(),
  snapshot_omitted: z.literal(true).exactOptional(),
  pre_batch: z.boolean(),
};

/** A receipt carries exactly one of `snapshot` and `snapshot_omitted`. */
function hasOneSnapshotForm(r: { readonly snapshot?: unknown; readonly snapshot_omitted?: true }): boolean {
  return (r.snapshot === undefined) !== (r.snapshot_omitted === undefined);
}

const SNAPSHOT_FORM = { message: 'a receipt carries snapshot or snapshot_omitted, not both or neither' };

export const BatchReceiptSchema = z.discriminatedUnion('state', [
  z
    .strictObject({
      ...receiptBase,
      state: z.literal('APPLIED'),
      applied: z.array(OpAppliedSchema).max(MAX_OPS_PER_BATCH),
      skipped: z.array(OpSkippedSchema).max(MAX_OPS_PER_BATCH),
    })
    .refine(hasOneSnapshotForm, SNAPSHOT_FORM),
  z
    .strictObject({
      ...receiptBase,
      state: z.literal('PARTIAL'),
      applied: z.array(OpAppliedSchema).max(MAX_OPS_PER_BATCH),
      skipped: z.array(OpSkippedSchema).max(MAX_OPS_PER_BATCH),
      failed: OpFailedSchema,
    })
    .refine(hasOneSnapshotForm, SNAPSHOT_FORM),
  z
    .strictObject({ ...receiptBase, state: z.literal('REJECTED'), reason: RejectReasonSchema, detail: DetailSchema.exactOptional() })
    .refine(hasOneSnapshotForm, SNAPSHOT_FORM),
]) satisfies z.ZodType<BatchReceipt>;

// --- Moves ---

export const MoveSchema = z.strictObject({
  node_id: NodeIdSchema,
  url: UrlSchema.exactOptional(),
  from: FolderPathSchema,
  to: FolderPathSchema,
  origin: MoveOriginSchema,
  observed_at: EpochMsSchema,
}) satisfies z.ZodType<Move>;

// --- Search, index and chat ---

export const LocalIndexRowSchema = z.strictObject({
  identity: IdentitySchema,
  title: TitleSchema,
  path: FolderPathSchema,
  tags: z.array(TagSchema).max(32),
  summary: text({ max: 512 }),
}) satisfies z.ZodType<LocalIndexRow>;

export const HitSchema = z.strictObject({
  identity: IdentitySchema,
  title: TitleSchema,
  path: FolderPathSchema,
  score: z.number().min(0).max(1),
  tier: HitTierSchema,
}) satisfies z.ZodType<Hit>;

export const EntryRefSchema = z.strictObject({
  identity: IdentitySchema,
  title: TitleSchema,
  path: FolderPathSchema,
}) satisfies z.ZodType<EntryRef>;

export const TurnSchema = z.strictObject({
  question: text({ min: 1, max: 8192 }),
  answer: text({ max: 65536 }),
}) satisfies z.ZodType<Turn>;

export const AnswerSchema = z.strictObject({
  text: text({ max: 65536 }),
  citations: z.array(EntryRefSchema).max(50),
  external_urls: z.array(UrlSchema).max(50),
}) satisfies z.ZodType<Answer>;

export const PlacementReasonSchema = z.strictObject({
  identity: IdentitySchema,
  folder: FolderPathSchema,
  neighbours: z.array(EntryRefSchema).max(50),
  rationale: text({ max: 8192 }),
  feedback_ids: z.array(IdSchema).max(50),
  model_id: text({ min: 1, max: 256 }),
  created_at: EpochMsSchema,
}) satisfies z.ZodType<PlacementReason>;

// --- Undo, batches list, diffs, outline ---

export const UndoDropSchema = z.strictObject({ index: OpIndexSchema, reason: UndoDropReasonSchema }) satisfies z.ZodType<UndoDrop>;

export const BatchSummarySchema = z.strictObject({
  batch_id: IdSchema,
  state: BatchStateSchema,
  created_at: EpochMsSchema,
  job_id: IdSchema.exactOptional(),
  identity: IdentitySchema.exactOptional(),
  diff_item_id: IdSchema.exactOptional(),
  undoes: IdSchema.exactOptional(),
  undone_by: IdSchema.exactOptional(),
});

export const TreeDiffSchema = z.strictObject({
  diff_id: IdSchema,
  kind: DiffKindSchema,
  proposed_at: EpochMsSchema,
  item_count: count(),
  unaccepted_count: count(),
}) satisfies z.ZodType<TreeDiff>;

export const DiffItemSchema = z.strictObject({
  item_id: IdSchema,
  diff_id: IdSchema,
  action: DiffActionSchema,
  description: text({ min: 1, max: 4096 }),
  operations: z.array(OperationSchema).min(1).max(MAX_OPS_PER_DIFF_ITEM),
  accepted_at: EpochMsSchema.nullable(),
  batch_id: IdSchema.exactOptional(),
  batch_state: BatchStateSchema.exactOptional(),
}) satisfies z.ZodType<DiffItem>;

export const OutlineFolderSchema = z.strictObject({
  node_id: NodeIdSchema,
  path: FolderPathSchema,
  pinned: z.boolean(),
  locked: z.boolean(),
  item_count: count(),
}) satisfies z.ZodType<OutlineFolder>;

export const ModelInfoSchema = z.strictObject({ id: text({ min: 1, max: 256 }), local: z.boolean() });
