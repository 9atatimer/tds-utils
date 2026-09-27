// daemonEvents.test.ts -- contract v1 README, "Delivery and replay" (design,
// "Transport contract", delivery): job.updated and diff.proposed are
// acknowledged by events.ack; the extension de-duplicates their side effects
// by event_id, and of two copies of one job keeps the higher seq whatever
// order they arrive in; a job.updated whose state is FILED or INDEXED
// re-pulls the LocalIndex, and one arriving during a pull does not restart
// it -- the pull finishes, then one more starts. A batch.offer is answered by
// its receipt, never by events.ack.

import { describe, expect, it } from 'vitest';
import { BatchLane } from '../../../src/app/batchLane.js';
import { DaemonEvents } from '../../../src/app/daemonEvents.js';
import type { Job, JobState } from '../../../src/domain/jobs.js';
import type { EventMessage, RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { scriptedDaemon } from '../../fixtures/daemon.js';
import { CONTEXT, DYNOMARK, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

function jobUpdated(event_id: string, state: JobState, seq: number, job_id = 'job-1'): EventMessage {
  const job: Job = { job_id, node_id: '42', identity: 'https://tokio.rs/', state, seq, attempts: 0, backfill: false };
  return { v: 1, type: 'job.updated', event_id, job };
}

const DIFF = { diff_id: 'diff-1', kind: 'rebuild' as const, proposed_at: 1, item_count: 2, unaccepted_count: 2 };

/** Lane stand-in for tests that never offer a batch. */
const NO_BATCHES = { offer: () => Promise.reject(new Error('no batch expected')) };

function setup() {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  w.connection().autoAnswer(scriptedDaemon({}));
  const events = new DaemonEvents(w.worker(), NO_BATCHES);
  return { w, events };
}

function sentOf(transport: FakeTransport, type: string): RequestMessage[] {
  return transport.sent.filter((r) => r.type === type);
}

/** What dynomark-host answers when no daemon listens (daemon README): busy, retry later. */
function daemonDown(r: RequestMessage): ResponseMessage {
  return { v: 1, type: 'error', re: r.id, code: 'busy', message: 'the dynomark daemon is not running' };
}

function acked(transport: FakeTransport): string[] {
  return transport.sent.flatMap((r) => (r.type === 'events.ack' ? r.event_ids : []));
}

// --- Tests ---

describe('Daemon events -- DaemonEvents(deps, lane).handle(event)', () => {
  it('Given a job.updated FILED, When handled, Then it is acknowledged, the job is kept and the index is re-pulled once', async () => {
    const { w, events } = setup();
    await events.handle(jobUpdated('evt-1', 'FILED', 3));
    await events.idle();
    expect(acked(w.connection())).toEqual(['evt-1']);
    expect(events.jobs().get('job-1')).toMatchObject({ state: 'FILED', seq: 3 });
    expect(sentOf(w.connection(), 'index.pull')).toHaveLength(1);
  });

  it('Given the same event twice, When handled, Then both copies are acknowledged but its side effect happens once', async () => {
    const { w, events } = setup();
    await events.handle(jobUpdated('evt-1', 'INDEXED', 2));
    await events.idle();
    await events.handle(jobUpdated('evt-1', 'INDEXED', 2));
    await events.idle();
    expect(acked(w.connection())).toEqual(['evt-1', 'evt-1']);
    expect(sentOf(w.connection(), 'index.pull')).toHaveLength(1);
  });

  it('Given two copies of one job arriving newer first, When handled, Then the higher seq is kept and the stale copy has no effect', async () => {
    const { w, events } = setup();
    await events.handle(jobUpdated('evt-9', 'FILED', 2));
    await events.handle(jobUpdated('evt-8', 'QUEUED', 1));
    await events.idle();
    expect(events.jobs().get('job-1')).toMatchObject({ state: 'FILED', seq: 2 });
    expect(acked(w.connection())).toEqual(['evt-9', 'evt-8']);
    expect(sentOf(w.connection(), 'index.pull')).toHaveLength(1);
  });

  it('Given two copies of one job arriving older first, When handled, Then the higher seq replaces it', async () => {
    const { events } = setup();
    await events.handle(jobUpdated('evt-1', 'QUEUED', 1));
    await events.handle(jobUpdated('evt-2', 'INDEXED', 2));
    await events.idle();
    expect(events.jobs().get('job-1')).toMatchObject({ state: 'INDEXED', seq: 2 });
  });

  it('Given a job.updated that is neither FILED nor INDEXED, When handled, Then it is acknowledged and the index is not pulled', async () => {
    const { w, events } = setup();
    await events.handle(jobUpdated('evt-1', 'PLACED', 4));
    await events.idle();
    expect(acked(w.connection())).toEqual(['evt-1']);
    expect(sentOf(w.connection(), 'index.pull')).toEqual([]);
  });

  it('Given two FILED updates arriving while a pull runs, When handled, Then the pull is not restarted and exactly one more follows it', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const daemon = w.daemon();
    const answer = scriptedDaemon({});
    const events = new DaemonEvents(w.worker(), NO_BATCHES);
    const serveUntilPull = async (): Promise<RequestMessage> => {
      for (;;) {
        const r = await daemon.nextRequest();
        if (r.type === 'index.pull') return r;
        await daemon.answer(answer(r));
      }
    };
    const first = events.handle(jobUpdated('evt-1', 'FILED', 1, 'job-1'));
    const pull1 = await serveUntilPull();
    await first;
    const second = events.handle(jobUpdated('evt-2', 'FILED', 1, 'job-2'));
    const third = events.handle(jobUpdated('evt-3', 'INDEXED', 1, 'job-3'));
    await daemon.answer(answer(await daemon.nextRequest()));
    await daemon.answer(answer(await daemon.nextRequest()));
    await Promise.all([second, third]);
    await daemon.answer(answer(pull1));
    const pull2 = await serveUntilPull();
    expect(pull2.id).not.toBe(pull1.id);
    await daemon.answer(answer(pull2));
    await events.idle();
    expect(sentOf(w.connection(), 'index.pull')).toHaveLength(2);
  });

  it('Given a diff.proposed twice, When handled, Then each copy is acknowledged and the diff is kept once', async () => {
    const { w, events } = setup();
    await events.handle({ v: 1, type: 'diff.proposed', event_id: 'evt-d', diff: DIFF });
    await events.handle({ v: 1, type: 'diff.proposed', event_id: 'evt-d', diff: DIFF });
    expect(acked(w.connection())).toEqual(['evt-d', 'evt-d']);
    expect([...events.diffs().values()]).toEqual([DIFF]);
  });

  it('Given a batch.offer, When handled, Then it is answered by a receipt from the lane and never by events.ack', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    await seedOwnedTree(w.tree);
    w.connection().autoAnswer(scriptedDaemon({}));
    const events = new DaemonEvents(w.worker(), new BatchLane(() => CONTEXT, w.worker()));
    await events.handle({
      v: 1,
      type: 'batch.offer',
      event_id: 'evt-b',
      batch: { batch_id: 'batch-1', operations: [{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }] },
    });
    expect(sentOf(w.connection(), 'batch.receipt')).toHaveLength(1);
    expect(acked(w.connection())).toEqual([]);
  });

  // Found by the integration e2e: a daemon restart between an event and its
  // ack left 'daemon error busy' in the settings page's problems for good.
  it('Given the daemon went down after pushing a job.updated (the host answers busy), When handled, Then it resolves quietly and its effect waits for the replay', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    w.connection().autoAnswer(daemonDown);
    const events = new DaemonEvents(w.worker(), NO_BATCHES);

    await expect(events.handle(jobUpdated('evt-1', 'FILED', 3))).resolves.toBeUndefined();
    await events.idle();
    expect(events.jobs().has('job-1')).toBe(false);
    expect(sentOf(w.connection(), 'index.pull')).toEqual([]);

    w.connection().autoAnswer(scriptedDaemon({}));
    await events.handle(jobUpdated('evt-1', 'FILED', 3));
    await events.idle();
    expect(events.jobs().get('job-1')).toMatchObject({ state: 'FILED', seq: 3 });
    expect(sentOf(w.connection(), 'index.pull')).toHaveLength(1);
  });

  it('Given the link is lost while a job.updated is acknowledged, When handled, Then it resolves quietly (the daemon replays it)', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    w.connection().unreachable(true);
    const events = new DaemonEvents(w.worker(), NO_BATCHES);

    await expect(events.handle(jobUpdated('evt-1', 'FILED', 3))).resolves.toBeUndefined();
    expect(events.jobs().has('job-1')).toBe(false);
  });

  it('Given the daemon answers the ack invalid, When handled, Then it rejects (only transport loss and retryable codes wait for a replay)', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    w.connection().autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'invalid', message: 'no' }));
    const events = new DaemonEvents(w.worker(), NO_BATCHES);

    await expect(events.handle(jobUpdated('evt-1', 'FILED', 3))).rejects.toThrow('invalid');
  });

  it('Given the daemon went down before a batch receipt reached it, When the offer is handled, Then it resolves quietly (the daemon re-offers it and the cursor answers)', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    await seedOwnedTree(w.tree);
    w.connection().autoAnswer((r) => (r.type === 'batch.receipt' ? daemonDown(r) : scriptedDaemon({})(r)));
    const events = new DaemonEvents(w.worker(), new BatchLane(() => CONTEXT, w.worker()));

    await expect(
      events.handle({
        v: 1,
        type: 'batch.offer',
        event_id: 'evt-b',
        batch: { batch_id: 'batch-1', operations: [{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }] },
      }),
    ).resolves.toBeUndefined();
    expect(sentOf(w.connection(), 'batch.receipt')).toHaveLength(1);
  });
});
