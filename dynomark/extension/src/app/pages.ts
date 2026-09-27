// pages.ts -- answering the extension pages (design, "Settings"; "A batch is
// undone"; State Machine, FAILED -> QUEUED on a user retry; "Chat surface").
// The options page reads the overview and edits the capture setting; the
// history page lists batches (Undo) and FAILED jobs (Retry); the chat page
// asks, explains, opens a citation and files a URL. Every daemon request goes
// through the runtime's one Connection; a refusal is answered ok: false with
// its code.

import type { Settings } from '../domain/settings.js';
import { capturesFromTab, capturesInBackground, type SettingsChange } from '../domain/settings.js';
import { isOpenable } from '../domain/search.js';
import type { FolderPath } from '../domain/tree.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { IdSource } from '../ports/idSource.js';
import type { Clock } from '../ports/clock.js';
import type { Navigator } from '../ports/navigator.js';
import type { Overview, PageRequest, PageResponse } from '../ports/pages.js';
import type { LinkState, TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { askQuestion, explainPlacement, fileThis } from './chat.js';
import type { HelloOutcome } from './connection.js';
import type { WriterWatch } from './writerWatch.js';
import { listDiffs, proposeDiff, readDiffPage, readOutline, setFolderFlags, type DiffAcceptance } from './diffs.js';
import { DaemonError, resultOrThrow } from './errors.js';

// --- Types ---

export interface PageContext {
  readonly transport: TransportPort;
  readonly ids: IdSource;
  readonly tree: BookmarkTreePort;
  readonly navigator: Navigator;
  readonly clock: Clock;
  readonly acceptance: DiffAcceptance;
  readonly writer: WriterWatch;
  link(): LinkState;
  outcome(): HelloOutcome | undefined;
  settings(): Settings;
  changeSettings(change: SettingsChange): Promise<Settings>;
  followUp(): FolderPath | undefined;
  problems(): readonly string[];
}

// --- Pure helpers ---

function failure(error: unknown): PageResponse {
  if (error instanceof DaemonError) return { ok: false, error: error.message, code: error.code };
  return { ok: false, error: error instanceof Error ? error.message : String(error) };
}

// --- Flow ---

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function daemonSection(context: PageContext): Promise<Pick<Overview, 'daemon' | 'daemon_error'>> {
  try {
    const status = resultOrThrow(await context.transport.send({ v: CONTRACT_VERSION, type: 'status', id: context.ids.next() }));
    const { role, host_id, contract_version, models, queue_depth } = status;
    return { daemon: { role, host_id, contract_version, models, queue_depth } };
  } catch (error) {
    return { daemon_error: message(error) };
  }
}

/** The writer status, asked afresh on a full connection (writer.status is not in the read-only set); else the last one known. */
async function writerSection(context: PageContext): Promise<Pick<Overview, 'writer' | 'writer_error'>> {
  const known = context.writer.status();
  const last = known === undefined ? {} : { writer: known };
  if (context.outcome()?.mode !== 'full') return last;
  try {
    return { writer: await context.writer.refresh(context) };
  } catch (error) {
    return { ...last, writer_error: message(error) };
  }
}

async function overview(context: PageContext): Promise<Overview> {
  const settings = context.settings();
  const followUp = context.followUp();
  const daemon = await daemonSection(context);
  const writer = await writerSection(context);
  const now = context.outcome();
  return {
    settings: {
      profile_id: settings.profile_id,
      capture_from_tab: capturesFromTab(settings),
      capture_in_background: capturesInBackground(settings),
    },
    problems: context.problems(),
    ...(followUp === undefined ? {} : { follow_up: followUp }),
    ...daemon,
    ...writer,
    link: context.link(),
    ...(now === undefined ? {} : { connection: { v: now.v, mode: now.mode, role: now.role, host_id: now.host_id } }),
  };
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
    case 'ask':
      return { ok: true, kind: 'ask', answer: await askQuestion(request.question, request.history, context) };
    case 'explain':
      return { ok: true, kind: 'explain', reason: await explainPlacement(request.identity, context) };
    case 'open':
      if (!isOpenable(request.url)) return { ok: false, error: 'only http(s) URLs are opened' };
      await context.navigator.open(request.url, 'newForegroundTab');
      return { ok: true, kind: 'open' };
    case 'file': {
      const followUp = context.followUp();
      if (followUp === undefined) return { ok: false, error: 'no Follow Up folder is watched' };
      return { ok: true, kind: 'file', ...(await fileThis(request.url, request.title, followUp, context)) };
    }
    case 'diff.list':
      return { ok: true, kind: 'diff.list', ...(await listDiffs(request.cursor, context)) };
    case 'diff.page':
      return { ok: true, kind: 'diff.page', ...(await readDiffPage(request.diff_id, request.cursor, context)) };
    case 'diff.propose':
      return { ok: true, kind: 'diff.propose', diff: await proposeDiff(request.diff_kind, context) };
    case 'diff.accept':
      return { ok: true, kind: 'diff.accept', ...(await context.acceptance.accept(request.item_id, context)) };
    case 'outline':
      return { ok: true, kind: 'outline', ...(await readOutline(request.cursor, context)) };
    case 'folder.flags': {
      const flags = {
        ...(request.pinned === undefined ? {} : { pinned: request.pinned }),
        ...(request.locked === undefined ? {} : { locked: request.locked }),
      };
      return { ok: true, kind: 'folder.flags', folder: await setFolderFlags(request, flags, context) };
    }
  }
}

/** Answer one page request; never throws. */
export async function answerPage(request: PageRequest, context: PageContext): Promise<PageResponse> {
  try {
    if (request.kind === 'overview') return { ok: true, kind: 'overview', overview: await overview(context) };
    if (request.kind === 'settings.set') {
      const { kind: _kind, ...change } = request;
      const settings = await context.changeSettings(change);
      return {
        ok: true,
        kind: 'settings.set',
        capture_from_tab: capturesFromTab(settings),
        capture_in_background: capturesInBackground(settings),
      };
    }
    return await ask(request, context);
  } catch (error) {
    return failure(error);
  }
}
