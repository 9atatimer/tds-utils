// ackBatch.test.ts -- design Behaviors row "A receipt is delivered":
// ack_batch(receipt, *, transport) -> none. Given a receipt, When delivered
// twice, Then the daemon records it once. Contract v1: `batch.receipt` is
// idempotent on receipt.batch_id (the first recorded wins); the extension
// keeps a batch's cursor until batch.receipt.result (or error not_found)
// for that batch arrives; a receipt that would not fit the 32 MiB frame
// carries snapshot_omitted instead of its snapshot.

import { describe, expect, it } from 'vitest';
import { ackBatch } from '../../../src/app/ackBatch.js';
import { DaemonError } from '../../../src/app/errors.js';
import type { BatchCursor, BatchReceipt } from '../../../src/domain/batch.js';
import { BatchReceiptMessageSchema, type RequestMessage, type ResponseMessage } from '../../../src/wire/messages.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';

// --- Builders ---

const SNAPSHOT = {
  taken_at: 1_790_000_001_000,
  root_ids: { bar: '1', other: '2', mobile: '3' },
  nodes: [
    { id: '0', parent_id: null, index: 0, kind: 'folder' as const, title: '', date_added: 1 },
    { id: '1', parent_id: '0', index: 0, kind: 'folder' as const, title: 'Bookmarks bar', date_added: 1 },
    { id: '2', parent_id: '0', index: 1, kind: 'folder' as const, title: 'Other bookmarks', date_added: 1 },
    { id: '3', parent_id: '0', index: 2, kind: 'folder' as const, title: 'Mobile bookmarks', date_added: 1 },
  ],
};

function receipt(batch_id = 'batch-0101'): BatchReceipt {
  return {
    state: 'APPLIED',
    batch_id,
    snapshot: SNAPSHOT,
    pre_batch: true,
    applied: [{ index: 0, node_id: '16', changed: true }],
    skipped: [],
  };
}

function cursorFor(batch_id: string): BatchCursor {
  return { batch_id, op_count: 1, next_index: 1, outcomes: [{ outcome: 'applied', index: 0, node_id: '16', changed: true }] };
}

/** A daemon that records the first receipt per batch_id and answers every one batch.receipt.result. */
function recordingDaemon(): { readonly recorded: Map<string, BatchReceipt>; readonly respond: (r: RequestMessage) => ResponseMessage } {
  const recorded = new Map<string, BatchReceipt>();
  const respond = (r: RequestMessage): ResponseMessage => {
    if (r.type !== 'batch.receipt') throw new Error(`unexpected ${r.type}`);
    if (!recorded.has(r.receipt.batch_id)) recorded.set(r.receipt.batch_id, r.receipt);
    return { v: 1, type: 'batch.receipt.result', re: r.id };
  };
  return { recorded, respond };
}

// --- Tests ---

describe('Behavior: A receipt is delivered -- ackBatch(receipt, { transport, ids, storage })', () => {
  it('Given a receipt, When delivered twice, Then both frames name its batch and the daemon records it once', async () => {
    const transport = new FakeTransport();
    const daemon = recordingDaemon();
    transport.autoAnswer(daemon.respond);
    const storage = new FakeStorage();
    await storage.saveCursor(cursorFor('batch-0101'));
    const deps = { transport, ids: new SequentialIdSource(), storage };
    await ackBatch(receipt(), deps);
    await ackBatch(receipt(), deps);
    expect(transport.sent.map((r) => (r.type === 'batch.receipt' ? r.receipt.batch_id : r.type))).toEqual(['batch-0101', 'batch-0101']);
    expect([...daemon.recorded.keys()]).toEqual(['batch-0101']);
    expect(await storage.loadCursor()).toBeUndefined();
  });

  it('Given the result has not arrived, When the receipt is in flight, Then the cursor is still held; When batch.receipt.result arrives, Then it is released', async () => {
    const transport = new FakeTransport();
    const storage = new FakeStorage();
    await storage.saveCursor(cursorFor('batch-0101'));
    const delivered = ackBatch(receipt(), { transport, ids: new SequentialIdSource(), storage });
    const request = await transport.daemon.nextRequest();
    expect(BatchReceiptMessageSchema.parse(request).receipt).toEqual(receipt());
    expect(await storage.loadCursor()).toMatchObject({ batch_id: 'batch-0101' });
    await transport.daemon.answer({ v: 1, type: 'batch.receipt.result', re: request.id });
    await delivered;
    expect(await storage.loadCursor()).toBeUndefined();
  });

  it('Given the daemon answers not_found for the batch, When delivered, Then the cursor is released all the same', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'not_found', message: 'no such batch' }));
    const storage = new FakeStorage();
    await storage.saveCursor(cursorFor('batch-0101'));
    await ackBatch(receipt(), { transport, ids: new SequentialIdSource(), storage });
    expect(await storage.loadCursor()).toBeUndefined();
  });

  it('Given the daemon answers another error, When delivered, Then it rejects with a DaemonError and the cursor is kept', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'internal', message: 'store busy' }));
    const storage = new FakeStorage();
    await storage.saveCursor(cursorFor('batch-0101'));
    await expect(ackBatch(receipt(), { transport, ids: new SequentialIdSource(), storage })).rejects.toBeInstanceOf(DaemonError);
    expect(await storage.loadCursor()).toMatchObject({ batch_id: 'batch-0101' });
  });

  it('Given the cursor names another batch, When a receipt result arrives, Then that cursor is left alone', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(recordingDaemon().respond);
    const storage = new FakeStorage();
    await storage.saveCursor(cursorFor('batch-0102'));
    await ackBatch(receipt('batch-0101'), { transport, ids: new SequentialIdSource(), storage });
    expect(await storage.loadCursor()).toMatchObject({ batch_id: 'batch-0102' });
  });

  it('Given a receipt whose frame would exceed the frame limit, When delivered, Then it carries snapshot_omitted instead of the snapshot', async () => {
    const transport = new FakeTransport();
    transport.autoAnswer(recordingDaemon().respond);
    await ackBatch(receipt(), { transport, ids: new SequentialIdSource(), storage: new FakeStorage() }, { max_frame_bytes: 300 });
    const frame = BatchReceiptMessageSchema.parse(transport.sent[0]);
    expect(frame.receipt).not.toHaveProperty('snapshot');
    expect(frame.receipt).toMatchObject({ snapshot_omitted: true, batch_id: 'batch-0101', state: 'APPLIED' });
  });
});
