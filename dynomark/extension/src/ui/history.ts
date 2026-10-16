// history.ts -- the history page: what Dynomark did to the tree, and what it
// could not do (design, Goal 6 "every APPLIED batch has an inverse"; State
// Machine, FAILED -> QUEUED "user retries"). Undo per APPLIED batch, Retry
// per FAILED job. A view over the background, holding no state of its own.

import type { UndoDrop } from '../domain/diff.js';
import type { Job } from '../domain/jobs.js';
import type { PageClient, PageResponse } from '../ports/pages.js';
import { byId, el, row, when } from './dom.js';

// --- Types ---

type BatchPage = Extract<PageResponse, { kind: 'batch.list' }>;
type Batch = BatchPage['batches'][number];

// --- Predicates ---

function isUndoable(batch: Batch): boolean {
  return batch.state === 'APPLIED' && batch.undone_by === undefined;
}

// --- Pure helpers ---

const DROP_REASON: Readonly<Record<UndoDrop['reason'], string>> = {
  node_moved: 'moved since',
  node_missing: 'gone since',
  not_empty: 'the folder holds other items now',
  locked: 'the folder is locked',
  owned_root: 'Dynomark and Graveyard are kept (an owned root)',
};

/** What a batch row says the batch did: an undo, a parked duplicate (naming the existing placement), a filing, or an accepted item. */
export function batchWhat(batch: Batch): string {
  if (batch.undoes !== undefined) return `undo of ${batch.undoes}`;
  const what = batch.identity ?? batch.diff_item_id ?? '';
  if (batch.park === undefined) return what;
  const where = [batch.park.existing.root, ...batch.park.existing.names].join(' / ').replace(/^bar \/ /, '');
  return `${what}: parked, already filed in ${where}`;
}

/** What an undo answer says: queued or nothing left, and each step left out with its reason. */
export function undoReport(batch_id: string, inverse: string | null, dropped: readonly UndoDrop[]): string {
  const head = inverse === null ? `undo ${batch_id}: nothing left to revert` : `undo ${batch_id} queued as ${inverse}`;
  if (dropped.length === 0) return head;
  return `${head}; not reverted: ${dropped.map((d) => `op ${d.index}: ${DROP_REASON[d.reason]}`).join(', ')}`;
}

// --- Rendering ---

function say(doc: Document, text: string): void {
  byId(doc, 'message').textContent = text;
}

function batchRow(doc: Document, client: PageClient, batch: Batch): HTMLElement {
  const what = batchWhat(batch);
  const action = el(doc, 'button', 'Undo', { 'data-batch': batch.batch_id });
  if (!isUndoable(batch)) action.setAttribute('disabled', '');
  action.addEventListener('click', () => void undo(doc, client, batch.batch_id));
  return row(doc, [when(batch.created_at), batch.batch_id, batch.state, what, action]);
}

function jobRow(doc: Document, client: PageClient, job: Job): HTMLElement {
  const action = el(doc, 'button', 'Retry', { 'data-job': job.job_id });
  action.addEventListener('click', () => void retry(doc, client, job.job_id));
  return row(doc, [job.identity, job.last_error ?? '', String(job.attempts), action]);
}

// --- Flow ---

async function loadBatches(doc: Document, client: PageClient, cursor?: string): Promise<void> {
  const response = await client.request(cursor === undefined ? { kind: 'batch.list' } : { kind: 'batch.list', cursor });
  if (!response.ok || response.kind !== 'batch.list') return say(doc, response.ok ? '' : `batches: ${response.error}`);
  const body = byId(doc, 'batches');
  const rows = response.batches.map((b) => batchRow(doc, client, b));
  if (cursor === undefined) body.replaceChildren(...rows);
  else body.append(...rows);
  const more = byId(doc, 'batches-more');
  more.hidden = response.next_cursor === null;
  more.onclick = response.next_cursor === null ? null : () => void loadBatches(doc, client, response.next_cursor ?? undefined);
}

/** One page of FAILED jobs, oldest first; a cursor gone stale (retries change the list) starts again from the first page. */
async function loadJobs(doc: Document, client: PageClient, cursor?: string): Promise<void> {
  const response = await client.request(cursor === undefined ? { kind: 'job.list' } : { kind: 'job.list', cursor });
  if (!response.ok && response.code === 'stale_cursor') return loadJobs(doc, client);
  if (!response.ok || response.kind !== 'job.list') return say(doc, response.ok ? '' : `jobs: ${response.error}`);
  const body = byId(doc, 'jobs');
  const rows = response.jobs.map((j) => jobRow(doc, client, j));
  if (cursor === undefined) body.replaceChildren(...rows);
  else body.append(...rows);
  const more = byId(doc, 'jobs-more');
  more.hidden = response.next_cursor === null;
  more.onclick = response.next_cursor === null ? null : () => void loadJobs(doc, client, response.next_cursor ?? undefined);
}

async function undo(doc: Document, client: PageClient, batch_id: string): Promise<void> {
  const response = await client.request({ kind: 'undo', batch_id });
  if (!response.ok) return say(doc, `undo ${batch_id}: ${response.error}`);
  if (response.kind === 'undo') say(doc, undoReport(batch_id, response.batch_id, response.dropped));
  await loadBatches(doc, client);
}

async function retry(doc: Document, client: PageClient, job_id: string): Promise<void> {
  const response = await client.request({ kind: 'job.retry', job_id });
  say(doc, response.ok ? `retry ${job_id}: queued` : `retry ${job_id}: ${response.error}`);
  await loadJobs(doc, client);
}

// --- Entry ---

/** Fill the page and wire its controls. */
export async function mountHistory(doc: Document, client: PageClient): Promise<void> {
  byId(doc, 'refresh').addEventListener('click', () => void Promise.all([loadBatches(doc, client), loadJobs(doc, client)]));
  await Promise.all([loadBatches(doc, client), loadJobs(doc, client)]);
}
