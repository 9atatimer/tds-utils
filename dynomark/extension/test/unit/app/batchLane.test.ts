// batchLane.test.ts -- contract v1 README, "One batch at a time", "Cursor and
// resume", "Delivery and replay" (extension side of the design's Transport
// contract, partial failure). Every batch.offer frame, a repeat included, is
// answered with a batch.receipt; the extension keeps a batch's cursor until
// batch.receipt.result for it arrives and starts no other batch before then:
// an offer of another batch is held and applied, in order, after it; the
// extension sends tree.snapshot right after every batch.receipt.result.
// Moves of nodes the open batch names are origin extension.

import { describe, expect, it } from 'vitest';
import { BatchLane } from '../../../src/app/batchLane.js';
import type { WriteBatch } from '../../../src/domain/batch.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { CONTEXT, DYNOMARK, RUST, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

function createBatch(batch_id: string, title: string): WriteBatch {
  return { batch_id, operations: [{ op: 'create_folder', index: 0, parent: DYNOMARK, title }] };
}

async function setup() {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  const ids = await seedOwnedTree(w.tree);
  const lane = new BatchLane(() => CONTEXT, w.worker());
  return { w, ids, lane };
}

function result(r: RequestMessage): ResponseMessage {
  if (r.type === 'batch.receipt') return { v: 1, type: 'batch.receipt.result', re: r.id };
  if (r.type === 'tree.snapshot') return { v: 1, type: 'tree.snapshot.result', re: r.id };
  throw new Error(`unexpected ${r.type}`);
}

/** The next request, which must be of `type`. */
async function expectNext(w: FakeExtensionWorld, type: string): Promise<RequestMessage> {
  const r = await w.daemon().nextRequest();
  expect(r.type).toBe(type);
  return r;
}

function receiptOf(r: RequestMessage) {
  if (r.type !== 'batch.receipt') throw new Error(`not a receipt: ${r.type}`);
  return r.receipt;
}

// --- Tests ---

describe('Batch offers -- BatchLane(context, deps).offer(batch)', () => {
  it('Given an offer, When it is answered, Then the batch is applied, its receipt sent, and after the result the cursor is released and tree.snapshot follows', async () => {
    const { w, lane } = await setup();
    const answered = lane.offer(createBatch('batch-1', 'Go'));
    const receipt = await expectNext(w, 'batch.receipt');
    expect(receiptOf(receipt)).toMatchObject({ state: 'APPLIED', batch_id: 'batch-1' });
    expect(await w.storage.loadCursor()).toMatchObject({ batch_id: 'batch-1' });
    await w.daemon().answer(result(receipt));
    const snapshot = await expectNext(w, 'tree.snapshot');
    await w.daemon().answer(result(snapshot));
    await answered;
    expect(await w.storage.loadCursor()).toBeUndefined();
  });

  it('Given the same offer twice before its result, When both are handled, Then each frame is answered with a receipt and the second comes from the cursor', async () => {
    const { w, lane } = await setup();
    const first = lane.offer(createBatch('batch-1', 'Go'));
    const r1 = await expectNext(w, 'batch.receipt');
    const second = lane.offer(createBatch('batch-1', 'Go'));
    const r2 = await expectNext(w, 'batch.receipt');
    expect(receiptOf(r1)).toMatchObject({ state: 'APPLIED', pre_batch: true, applied: [{ index: 0, changed: true }] });
    expect(receiptOf(r2)).toMatchObject({ state: 'APPLIED', pre_batch: false, applied: [{ index: 0, changed: true }] });
    expect(r2.id).not.toBe(r1.id);
    await w.daemon().answer(result(r1));
    await w.daemon().answer(result(r2));
    for (let i = 0; i < 2; i += 1) await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await Promise.all([first, second]);
    expect((await w.tree.getChildren((await w.worker().tree.resolveFolder(DYNOMARK)) ?? '')).filter((n) => n.title === 'Go')).toHaveLength(
      1,
    );
  });

  it('Given batch A awaits its result, When batch B is offered, Then B is held untouched until A is acknowledged, then applied', async () => {
    const { w, lane } = await setup();
    const a = lane.offer(createBatch('batch-A', 'Go'));
    const receiptA = await expectNext(w, 'batch.receipt');
    const b = lane.offer(createBatch('batch-B', 'Zig'));
    await Promise.resolve();
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Zig'] })).toBeUndefined();
    await w.daemon().answer(result(receiptA));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    const receiptB = await expectNext(w, 'batch.receipt');
    expect(receiptOf(receiptB)).toMatchObject({ state: 'APPLIED', batch_id: 'batch-B' });
    await w.daemon().answer(result(receiptB));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await Promise.all([a, b]);
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Zig'] })).toBeDefined();
  });

  it('Given a REJECTED batch awaiting its result, When another batch is offered, Then that one is held until the rejection is acknowledged', async () => {
    const { w, lane } = await setup();
    const rejected = lane.offer({
      batch_id: 'batch-R',
      operations: [{ op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Loot' }],
    });
    const receiptR = await expectNext(w, 'batch.receipt');
    expect(receiptOf(receiptR)).toMatchObject({ state: 'REJECTED', reason: 'boundary' });
    const next = lane.offer(createBatch('batch-N', 'Go'));
    await Promise.resolve();
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Go'] })).toBeUndefined();
    await w.daemon().answer(result(receiptR));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    const receiptN = await expectNext(w, 'batch.receipt');
    await w.daemon().answer(result(receiptN));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await Promise.all([rejected, next]);
    expect(receiptOf(receiptN)).toMatchObject({ state: 'APPLIED', batch_id: 'batch-N' });
  });

  it('Given batch A applied and its result lost to a restart, When the daemon offers batch B, Then A is answered again from its cursor, and B runs once A is acknowledged', async () => {
    const { w, ids } = await setup();
    const oldLane = new BatchLane(() => CONTEXT, w.worker());
    void oldLane
      .offer({
        batch_id: 'batch-A',
        operations: [{ op: 'move', index: 0, node_id: ids.saved, to: RUST, expect: { parent_id: ids.followUp } }],
      })
      .catch(() => undefined);
    await expectNext(w, 'batch.receipt');
    const worker = w.restart();
    const lane = new BatchLane(() => CONTEXT, worker);
    const b = lane.offer(createBatch('batch-B', 'Zig'));
    const again = await expectNext(w, 'batch.receipt');
    expect(receiptOf(again)).toMatchObject({
      state: 'APPLIED',
      batch_id: 'batch-A',
      pre_batch: false,
      applied: [{ index: 0, node_id: ids.saved, changed: true }],
    });
    await w.daemon().answer(result(again));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    const receiptB = await expectNext(w, 'batch.receipt');
    expect(receiptOf(receiptB)).toMatchObject({ batch_id: 'batch-B', state: 'APPLIED' });
    await w.daemon().answer(result(receiptB));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await b;
  });

  it('Given a batch whose move is open, When moves are observed, Then its node is in flight until the result arrives, and none after', async () => {
    const { w, ids, lane } = await setup();
    const done = lane.offer({
      batch_id: 'batch-M',
      operations: [{ op: 'move', index: 0, node_id: ids.saved, to: RUST, expect: { parent_id: ids.followUp } }],
    });
    const receipt = await expectNext(w, 'batch.receipt');
    expect([...lane.inFlight()]).toEqual([ids.saved]);
    await w.daemon().answer(result(receipt));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await done;
    expect([...lane.inFlight()]).toEqual([]);
  });

  it('Given the daemon answers the receipt with an error, When offered, Then that offer rejects, the cursor is kept, and a re-offer of the batch is answered', async () => {
    const { w, lane } = await setup();
    const failed = lane.offer(createBatch('batch-1', 'Go'));
    const r1 = await expectNext(w, 'batch.receipt');
    await w.daemon().answer({ v: 1, type: 'error', re: r1.id, code: 'internal', message: 'store busy' });
    await expect(failed).rejects.toMatchObject({ code: 'internal' });
    expect(await w.storage.loadCursor()).toMatchObject({ batch_id: 'batch-1' });
    const retried = lane.offer(createBatch('batch-1', 'Go'));
    const r2 = await expectNext(w, 'batch.receipt');
    await w.daemon().answer(result(r2));
    await w.daemon().answer(result(await expectNext(w, 'tree.snapshot')));
    await retried;
    expect(await w.storage.loadCursor()).toBeUndefined();
  });
});
