// runtime.pages.test.ts -- what the extension pages ask the background for
// (design, "Settings"; State Machine: FAILED -> QUEUED "user retries";
// "A batch is undone"): the options page shows the transport and daemon
// status and edits the capture setting; the history page lists batches with
// Undo and failed jobs with Retry. Daemon refusals come back as ok: false
// with the contract's error code.

import { describe, expect, it } from 'vitest';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { HOST_ID } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

const FAILED_JOB = {
  job_id: 'job-7',
  node_id: '42',
  identity: 'https://tokio.rs/',
  state: 'FAILED' as const,
  seq: 4,
  attempts: 3,
  backfill: false,
  last_error: 'completion timed out',
};

function answers(r: RequestMessage): ResponseMessage | undefined {
  switch (r.type) {
    case 'batch.list':
      return {
        v: 1,
        type: 'batch.list.result',
        re: r.id,
        batches: [{ batch_id: 'batch-1', state: 'APPLIED', created_at: 5, identity: 'https://tokio.rs/' }],
        next_cursor: 'page-2',
      };
    case 'undo':
      return r.batch_id === 'batch-1'
        ? { v: 1, type: 'undo.result', re: r.id, batch_id: 'batch-2', undoes: 'batch-1', dropped: [] }
        : { v: 1, type: 'error', re: r.id, code: 'not_found', message: 'no such batch' };
    case 'job.list':
      return { v: 1, type: 'job.list.result', re: r.id, jobs: [FAILED_JOB], next_cursor: null };
    case 'job.retry':
      return { v: 1, type: 'job.retry.result', re: r.id, job: { ...FAILED_JOB, state: 'QUEUED', seq: 5 } };
    default:
      return undefined;
  }
}

async function setup(): Promise<{ w: FakeExtensionWorld; runtime: ExtensionRuntime }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w, {}, answers);
  return { w, runtime: await startRuntime(w) };
}

// --- Tests ---

describe('Options page -- overview', () => {
  it('Given a connected writer, When the overview is asked for, Then it carries the link, the hello outcome, the daemon status and the settings', async () => {
    const { w, runtime } = await setup();
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({
      ok: true,
      kind: 'overview',
      overview: {
        link: { state: 'connected' },
        connection: { mode: 'full', role: 'writer', host_id: HOST_ID },
        daemon: { role: 'writer', host_id: HOST_ID, queue_depth: 2, models: { embedding: { id: 'nomic-embed-text' } } },
        settings: { capture_from_tab: true },
        follow_up: { root: 'bar', names: ['Follow Up'] },
      },
    });
    expect(sentOf(w, 'status')).toHaveLength(1);
  });

  it('Given an unreachable daemon, When the overview is asked for, Then it still answers, with the link down and the daemon error', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, {}, answers);
    w.connection().unreachable(true);
    const runtime = await startRuntime(w);
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({ ok: true, overview: { link: { state: 'disconnected' } } });
    expect(page.ok && page.kind === 'overview' ? page.overview.daemon_error : undefined).toBeTruthy();
  });
});

describe('History page -- batches with Undo, failed jobs with Retry', () => {
  it('Given the history page, When it lists batches, Then batch.list is sent and its page comes back with the cursor', async () => {
    const { w, runtime } = await setup();
    const page = await runtime.page({ kind: 'batch.list' });
    expect(page).toMatchObject({
      ok: true,
      kind: 'batch.list',
      batches: [{ batch_id: 'batch-1', state: 'APPLIED' }],
      next_cursor: 'page-2',
    });
    await runtime.page({ kind: 'batch.list', cursor: 'page-2' });
    expect(sentOf(w, 'batch.list').map((r) => r.cursor)).toEqual([undefined, 'page-2']);
  });

  it('Given an APPLIED batch, When Undo is pressed, Then undo is sent and the inverse batch id comes back', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'undo', batch_id: 'batch-1' })).toEqual({ ok: true, kind: 'undo', batch_id: 'batch-2', dropped: [] });
    expect(sentOf(w, 'undo').map((r) => r.batch_id)).toEqual(['batch-1']);
  });

  it('Given the daemon refuses an undo, When pressed, Then the page gets ok false with the error code', async () => {
    const { runtime } = await setup();
    expect(await runtime.page({ kind: 'undo', batch_id: 'batch-9' })).toMatchObject({ ok: false, code: 'not_found' });
  });

  it('Given the history page, When it lists jobs, Then job.list asks for FAILED jobs only', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'job.list' })).toMatchObject({ ok: true, kind: 'job.list', jobs: [{ job_id: 'job-7' }] });
    expect(sentOf(w, 'job.list')[0]?.state).toBe('FAILED');
  });

  it('Given a FAILED job, When Retry is pressed, Then job.retry is sent and the queued job comes back', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'job.retry', job_id: 'job-7' })).toMatchObject({ ok: true, job: { state: 'QUEUED' } });
    expect(sentOf(w, 'job.retry').map((r) => r.job_id)).toEqual(['job-7']);
  });
});
