// applyBatch.partial.test.ts -- design Behaviors row "A batch fails midway":
// Given operation 3 fails, When applied, Then the receipt is PARTIAL with the
// applied prefix. Contract v1, "Write batches": an op whose target folder
// does not resolve, or that the browser refuses, fails; the batch stops;
// `applied` and `skipped` partition 0..failed.index-1 and later ops were not
// tried. PARTIAL is not retried automatically; a re-offer resumes from the
// cursor at the failed op.

import { describe, expect, it } from 'vitest';
import { applyBatch } from '../../../src/app/applyBatch.js';
import type { WriteBatch } from '../../../src/domain/batch.js';
import { BatchReceiptSchema } from '../../../src/wire/values.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { CONTEXT, DYNOMARK, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const FIVE_FOLDERS: WriteBatch = {
  batch_id: 'batch-5',
  operations: ['A', 'B', 'C', 'D', 'E'].map((title, index) => ({ op: 'create_folder' as const, index, parent: DYNOMARK, title })),
};

async function world() {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  return { w, ids: await seedOwnedTree(w.tree) };
}

// --- Tests ---

describe('Behavior: A batch fails midway -- applyBatch when an operation fails', () => {
  it('Given operation 3 is refused by the browser, When applied, Then the receipt is PARTIAL with the applied prefix and later ops were not tried', async () => {
    const { w, ids } = await world();
    const before = await w.tree.readTree();
    w.tree.failOnMutation(3, 'refuse');
    const receipt = await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    expect(receipt).toMatchObject({
      state: 'PARTIAL',
      applied: [
        { index: 0, changed: true },
        { index: 1, changed: true },
      ],
      skipped: [],
      failed: { index: 2, reason: 'browser_error' },
      pre_batch: true,
    });
    expect(receipt.snapshot).toEqual({ ...before, taken_at: w.clock.now() });
    expect((await w.tree.getChildren(ids.dynomark)).map((n) => n.title)).toEqual(['Rust', 'A', 'B']);
    expect(() => BatchReceiptSchema.parse(receipt)).not.toThrow();
  });

  it('Given an operation whose target folder does not resolve, When applied, Then it fails parent_missing and the batch stops there', async () => {
    const { w } = await world();
    const batch: WriteBatch = {
      batch_id: 'batch-6',
      operations: [
        { op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' },
        { op: 'create_folder', index: 1, parent: { root: 'bar', names: ['Dynomark', 'Missing'] }, title: 'Deep' },
        { op: 'create_folder', index: 2, parent: DYNOMARK, title: 'Never' },
      ],
    };
    const receipt = await applyBatch(batch, CONTEXT, w.worker());
    expect(receipt).toMatchObject({ state: 'PARTIAL', applied: [{ index: 0 }], failed: { index: 1, reason: 'parent_missing' } });
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Never'] })).toBeUndefined();
  });

  it('Given the first operation fails, When applied, Then the receipt is PARTIAL with an empty prefix', async () => {
    const { w } = await world();
    w.tree.failOnMutation(1, 'refuse');
    expect(await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker())).toMatchObject({
      state: 'PARTIAL',
      applied: [],
      skipped: [],
      failed: { index: 0 },
    });
  });

  it('Given a PARTIAL batch, When it is offered again and the browser now accepts, Then the prefix is not repeated and the failed op onward runs to APPLIED', async () => {
    const { w, ids } = await world();
    w.tree.failOnMutation(3, 'refuse');
    await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    const again = await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    expect(again).toMatchObject({ state: 'APPLIED', pre_batch: false });
    expect(again.state === 'APPLIED' ? again.applied.map((a) => a.changed) : []).toEqual([true, true, true, true, true]);
    expect((await w.tree.getChildren(ids.dynomark)).map((n) => n.title)).toEqual(['Rust', 'A', 'B', 'C', 'D', 'E']);
  });

  it('Given a PARTIAL batch, When its receipt is not yet acknowledged, Then the durable cursor still names the batch and records the failure', async () => {
    const { w } = await world();
    w.tree.failOnMutation(3, 'refuse');
    await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    expect(await w.storage.loadCursor()).toMatchObject({
      batch_id: 'batch-5',
      next_index: 2,
      failed: { index: 2, reason: 'browser_error' },
    });
  });
});
