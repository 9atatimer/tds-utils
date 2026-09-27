// applyBatch.test.ts -- design Behaviors row "A batch is applied":
// apply_batch(batch, *, tree) -> BatchReceipt. Given a batch, When applied,
// Then a snapshot is read first, operations run in order, and the receipt is
// APPLIED with a node id per operation. Contract v1, "Write batches": the
// receipt carries the full tree read at the start of the attempt, and
// `pre_batch` true when no op of the batch had changed the tree before it.

import { describe, expect, it } from 'vitest';
import { applyBatch } from '../../../src/app/applyBatch.js';
import type { WriteBatch } from '../../../src/domain/batch.js';
import { BatchReceiptSchema } from '../../../src/wire/values.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { CONTEXT, DYNOMARK, FOLLOW_UP, RUST, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

async function world() {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  return { w, ids: await seedOwnedTree(w.tree) };
}

function fileBatch(saved: string, followUp: string): WriteBatch {
  return {
    batch_id: 'batch-0101',
    operations: [
      { op: 'create_folder', index: 0, parent: RUST, title: 'Async' },
      {
        op: 'move',
        index: 1,
        node_id: saved,
        to: { root: 'bar', names: ['Dynomark', 'Rust', 'Async'] },
        expect: { parent_id: followUp, parent_path: FOLLOW_UP },
      },
    ],
  };
}

// --- Tests ---

describe('Behavior: A batch is applied -- applyBatch(batch, context, { tree, storage, clock })', () => {
  it('Given a filing batch, When applied, Then the receipt is APPLIED with a node id per operation and the tree holds the result', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(fileBatch(ids.saved, ids.followUp), CONTEXT, w.worker());
    const tree = await w.tree.readTree();
    const asyncFolder = tree.nodes.find((n) => n.kind === 'folder' && n.title === 'Async');
    expect(asyncFolder?.parent_id).toBe(ids.rust);
    expect(receipt).toMatchObject({
      state: 'APPLIED',
      batch_id: 'batch-0101',
      applied: [
        { index: 0, node_id: asyncFolder?.id, changed: true },
        { index: 1, node_id: ids.saved, changed: true },
      ],
      skipped: [],
    });
    expect(tree.nodes.find((n) => n.id === ids.saved)?.parent_id).toBe(asyncFolder?.id);
  });

  it('Given a batch, When applied, Then the receipt carries the tree as read before the first operation, stamped now, with pre_batch true', async () => {
    const { w, ids } = await world();
    const before = await w.tree.readTree();
    const receipt = await applyBatch(fileBatch(ids.saved, ids.followUp), CONTEXT, w.worker());
    expect(receipt.pre_batch).toBe(true);
    expect(receipt.snapshot).toEqual({ ...before, taken_at: w.clock.now() });
  });

  it('Given an operation that depends on the one before it, When applied, Then operations run in order', async () => {
    const { w } = await world();
    const batch: WriteBatch = {
      batch_id: 'batch-2',
      operations: [
        { op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' },
        { op: 'create_folder', index: 1, parent: { root: 'bar', names: ['Dynomark', 'Go'] }, title: 'Generics' },
        {
          op: 'create',
          index: 2,
          parent: { root: 'bar', names: ['Dynomark', 'Go', 'Generics'] },
          title: 'Tour',
          url: 'https://go.dev/tour/',
        },
      ],
    };
    const receipt = await applyBatch(batch, CONTEXT, w.worker());
    expect(receipt.state).toBe('APPLIED');
    const created = await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Go', 'Generics'] });
    const children = await w.tree.getChildren(created ?? '');
    expect(children).toMatchObject([{ kind: 'bookmark', title: 'Tour', url: 'https://go.dev/tour/' }]);
    expect(receipt).toMatchObject({ applied: [{ index: 0 }, { index: 1, node_id: created }, { index: 2, node_id: children[0]?.id }] });
  });

  it('Given a remove, When applied, Then the node is moved to the end of the graveyard, never deleted', async () => {
    const { w, ids } = await world();
    const batch: WriteBatch = {
      batch_id: 'batch-3',
      operations: [{ op: 'remove', index: 0, node_id: ids.saved, expect: { parent_id: ids.followUp } }],
    };
    const receipt = await applyBatch(batch, CONTEXT, w.worker());
    expect(receipt).toMatchObject({ state: 'APPLIED', applied: [{ index: 0, node_id: ids.saved, changed: true }] });
    expect(await w.tree.getNode(ids.saved)).toMatchObject({ parent_id: ids.graveyard });
  });

  it('Given an applied batch, When its receipt is validated, Then it is a valid contract v1 BatchReceipt', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(fileBatch(ids.saved, ids.followUp), CONTEXT, w.worker());
    expect(() => BatchReceiptSchema.parse(receipt)).not.toThrow();
  });

  it('Given a folder title with a lone surrogate and one over 4,096 code points, When the snapshot is read, Then it is well-formed, cut to the cap and marked truncated', async () => {
    const { w, ids } = await world();
    const odd = await w.tree.createFolder(ids.dynomark, 'Half \uD83E');
    const long = await w.tree.createFolder(ids.dynomark, 'L'.repeat(5000));
    const receipt = await applyBatch(fileBatch(ids.saved, ids.followUp), CONTEXT, w.worker());
    const nodes = receipt.snapshot?.nodes ?? [];
    expect(nodes.find((n) => n.id === odd.id)).toMatchObject({ title: 'Half �' });
    expect(nodes.find((n) => n.id === long.id)).toMatchObject({ title: 'L'.repeat(4096), truncated: true });
    expect(() => BatchReceiptSchema.parse(receipt)).not.toThrow();
  });
});
