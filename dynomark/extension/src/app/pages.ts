// pages.ts -- answering the extension pages (design, "Settings"; "A batch is
// undone"; State Machine, FAILED -> QUEUED on a user retry). The options page
// reads the overview and edits the capture setting; the history page lists
// batches (Undo) and FAILED jobs (Retry). Every daemon request goes through
// the runtime's one Connection; a refusal is answered ok: false with its code.

import type { Settings } from '../domain/settings.js';
import { capturesFromTab } from '../domain/settings.js';
import type { FolderPath } from '../domain/tree.js';
import type { IdSource } from '../ports/idSource.js';
import type { Overview, PageRequest, PageResponse } from '../ports/pages.js';
import type { LinkState, TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import type { HelloOutcome } from './connection.js';
import { DaemonError, resultOrThrow } from './errors.js';

// --- Types ---

export interface PageContext {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  link(): LinkState;
  outcome(): HelloOutcome | undefined;
  settings(): Settings;
  setCaptureFromTab(value: boolean): Promise<Settings>;
  followUp(): FolderPath | undefined;
  problems(): readonly string[];
}

// --- Pure helpers ---

function failure(error: unknown): PageResponse {
  if (error instanceof DaemonError) return { ok: false, error: error.message, code: error.code };
  return { ok: false, error: error instanceof Error ? error.message : String(error) };
}

// --- Flow ---

async function overview(context: PageContext): Promise<Overview> {
  const outcome = context.outcome();
  const settings = context.settings();
  const followUp = context.followUp();
  const base = {
    settings: { profile_id: settings.profile_id, capture_from_tab: capturesFromTab(settings) },
    problems: context.problems(),
    ...(followUp === undefined ? {} : { follow_up: followUp }),
  };
  try {
    const status = resultOrThrow(await context.transport.send({ v: CONTRACT_VERSION, type: 'status', id: context.ids.next() }));
    const { role, host_id, contract_version, models, queue_depth } = status;
    const now = context.outcome() ?? outcome;
    return {
      ...base,
      link: context.link(),
      daemon: { role, host_id, contract_version, models, queue_depth },
      ...(now === undefined ? {} : { connection: { v: now.v, mode: now.mode, role: now.role, host_id: now.host_id } }),
    };
  } catch (error) {
    const now = context.outcome();
    return {
      ...base,
      link: context.link(),
      daemon_error: error instanceof Error ? error.message : String(error),
      ...(now === undefined ? {} : { connection: { v: now.v, mode: now.mode, role: now.role, host_id: now.host_id } }),
    };
  }
}

async function ask(request: Exclude<PageRequest, { kind: 'overview' | 'settings.set' }>, context: PageContext): Promise<PageResponse> {
  const id = context.ids.next();
  const v = CONTRACT_VERSION;
  const cursor = (c: string | undefined) => (c === undefined ? {} : { cursor: c });
  switch (request.kind) {
    case 'batch.list': {
      const r = resultOrThrow(await context.transport.send({ v, type: 'batch.list', id, ...cursor(request.cursor) }));
      return { ok: true, kind: 'batch.list', batches: r.batches, next_cursor: r.next_cursor };
    }
    case 'undo': {
      const r = resultOrThrow(await context.transport.send({ v, type: 'undo', id, batch_id: request.batch_id }));
      return { ok: true, kind: 'undo', batch_id: r.batch_id, dropped: r.dropped };
    }
    case 'job.list': {
      const r = resultOrThrow(await context.transport.send({ v, type: 'job.list', id, state: 'FAILED', ...cursor(request.cursor) }));
      return { ok: true, kind: 'job.list', jobs: r.jobs, next_cursor: r.next_cursor };
    }
    case 'job.retry': {
      const r = resultOrThrow(await context.transport.send({ v, type: 'job.retry', id, job_id: request.job_id }));
      return { ok: true, kind: 'job.retry', job: r.job };
    }
  }
}

/** Answer one page request; never throws. */
export async function answerPage(request: PageRequest, context: PageContext): Promise<PageResponse> {
  try {
    if (request.kind === 'overview') return { ok: true, kind: 'overview', overview: await overview(context) };
    if (request.kind === 'settings.set') {
      const settings = await context.setCaptureFromTab(request.capture_from_tab);
      return { ok: true, kind: 'settings.set', capture_from_tab: capturesFromTab(settings) };
    }
    return await ask(request, context);
  } catch (error) {
    return failure(error);
  }
}
