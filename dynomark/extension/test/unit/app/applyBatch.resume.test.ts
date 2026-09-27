// applyBatch.resume.test.ts -- design Behaviors row "A batch resumes after
// termination": Given a cursor at operation 3 of 5, When the same batch is
// offered again, Then operations 1-3 are not repeated and the receipt is
// APPLIED. Contract v1, "Cursor and resume": recorded outcomes are reported,
// never re-derived from the tree; an op marked started is re-evaluated by
// its post-condition; a fully applied batch is answered APPLIED again
// without touching the tree; one durable cursor, held until the receipt's
// result (design: durable extension state is exactly settings, the
// LocalIndex and the in-flight batch cursor).

import { describe, expect, it } from 'vitest';
import { CursorHeld, applyBatch } from '../../../src/app/applyBatch.js';
import type { WriteBatch } from '../../../src/domain/batch.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { WorkerTerminated } from '../../fakes/WorkerTerminated.js';
import { CONTEXT, DYNOMARK, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const FIVE_FOLDERS: WriteBatch = {
  batch_id: 'batch-5',
  operations: ['A', 'B', 'C', 'D', 'E'].map((title, index) => ({ op: 'create_folder' as const, index, parent: DYNOMARK, title })),
};

async function titlesUnderDynomark(w: FakeExtensionWorld, dynomark: string): Promise<string[]> {
  return (await w.tree.getChildren(dynomark)).map((n) => n.title);
}

// --- Tests ---

describe('Behavior: A batch resumes after termination -- applyBatch re-offered after a service-worker restart', () => {
  it('Given the worker died with the cursor at op 3 of 5, When the batch is offered to a new worker, Then ops 0-2 are reported from the cursor (not repeated) and the receipt is APPLIED', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const ids = await seedOwnedTree(w.tree);
    w.tree.failOnMutation(4, 'terminate-before');
    await expect(applyBatch(FIVE_FOLDERS, CONTEXT, w.worker())).rejects.toBeInstanceOf(WorkerTerminated);
    expect(await titlesUnderDynomark(w, ids.dynomark)).toEqual(['Rust', 'A', 'B', 'C']);

    const receipt = await applyBatch(FIVE_FOLDERS, CONTEXT, w.restart());
    expect(receipt.state).toBe('APPLIED');
    expect(receipt.state === 'APPLIED' ? receipt.applied.map((a) => [a.index, a.changed]) : []).toEqual([
      [0, true],
      [1, true],
      [2, true],
      [3, true],
      [4, true],
    ]);
    expect(receipt.pre_batch).toBe(false);
    expect(await titlesUnderDynomark(w, ids.dynomark)).toEqual(['Rust', 'A', 'B', 'C', 'D', 'E']);
  });

  it('Given the browser made op 3 but the worker died before recording it, When re-offered, Then op 3 is re-evaluated by its post-condition: applied, changed, not made twice', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const ids = await seedOwnedTree(w.tree);
    w.tree.failOnMutation(4, 'terminate-after');
    await expect(applyBatch(FIVE_FOLDERS, CONTEXT, w.worker())).rejects.toBeInstanceOf(WorkerTerminated);
    const madeD = (await w.tree.getChildren(ids.dynomark)).find((n) => n.title === 'D');

    const receipt = await applyBatch(FIVE_FOLDERS, CONTEXT, w.restart());
    expect(receipt).toMatchObject({ state: 'APPLIED', applied: expect.arrayContaining([{ index: 3, node_id: madeD?.id, changed: true }]) });
    expect(await titlesUnderDynomark(w, ids.dynomark)).toEqual(['Rust', 'A', 'B', 'C', 'D', 'E']);
  });

  it('Given a batch fully applied, When it is offered again, Then it is answered APPLIED from the recorded outcomes without touching the tree', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const ids = await seedOwnedTree(w.tree);
    const first = await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    await w.tree.move((await w.tree.getChildren(ids.dynomark)).find((n) => n.title === 'B')?.id ?? '', ids.graveyard);
    w.tree.failOnMutation(1, 'refuse');
    w.clock.advance(5000);

    const again = await applyBatch(FIVE_FOLDERS, CONTEXT, w.restart());
    expect(again.state === 'APPLIED' && first.state === 'APPLIED' ? again.applied : 'not applied').toEqual(
      first.state === 'APPLIED' ? first.applied : [],
    );
    expect(again.pre_batch).toBe(false);
    expect(again.snapshot?.taken_at).toBe(w.clock.now());
    expect(await titlesUnderDynomark(w, ids.dynomark)).toEqual(['Rust', 'A', 'C', 'D', 'E']);
  });

  it('Given a batch applied, When the receipt is not yet acknowledged, Then the durable cursor names the batch with every op recorded', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    await seedOwnedTree(w.tree);
    await applyBatch(FIVE_FOLDERS, CONTEXT, w.worker());
    expect(await w.storage.loadCursor()).toMatchObject({ batch_id: 'batch-5', next_index: 5 });
  });

  it('Given the cursor is held by another batch, When a batch is applied, Then it is refused (CursorHeld) and the tree is untouched', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const ids = await seedOwnedTree(w.tree);
    await w.storage.saveCursor({
      batch_id: 'batch-other',
      op_count: 1,
      next_index: 1,
      outcomes: [{ outcome: 'applied', index: 0, node_id: ids.rust, changed: true }],
    });
    await expect(applyBatch(FIVE_FOLDERS, CONTEXT, w.worker())).rejects.toBeInstanceOf(CursorHeld);
    expect(await titlesUnderDynomark(w, ids.dynomark)).toEqual(['Rust']);
    expect(await w.storage.loadCursor()).toMatchObject({ batch_id: 'batch-other' });
  });
});
