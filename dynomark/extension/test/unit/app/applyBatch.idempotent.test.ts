// applyBatch.idempotent.test.ts -- task-024 row 8 and design glossary
// "Operation": each is path-idempotent (create if absent, move if not
// already there). Contract v1, "Write batches": a create is a no-op when an
// exact child already exists (applied, changed false); a move or remove
// already directly in its target is a no-op and `expect` is not evaluated;
// otherwise every `expect` clause is checked and a failed clause, or a node
// that no longer exists, skips the op (SkipReason) and the batch continues.

import { describe, expect, it } from 'vitest';
import { applyBatch } from '../../../src/app/applyBatch.js';
import type { BatchReceipt, WriteBatch } from '../../../src/domain/batch.js';
import { BatchReceiptSchema } from '../../../src/wire/values.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { CONTEXT, DYNOMARK, FOLLOW_UP, GRAVEYARD, RUST, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

async function world() {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  return { w, ids: await seedOwnedTree(w.tree) };
}

function batch(...operations: WriteBatch['operations']): WriteBatch {
  return { batch_id: 'batch-idem', operations };
}

function outcomes(receipt: BatchReceipt): unknown {
  return receipt.state === 'REJECTED' ? receipt : { applied: receipt.applied, skipped: receipt.skipped };
}

// --- Tests ---

describe('Operations are path-idempotent -- applyBatch against what the tree already holds', () => {
  it('Given a child folder with the exact title exists, When create_folder applies, Then it is applied unchanged with that folder id and no folder is added', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(batch({ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Rust' }), CONTEXT, w.worker());
    expect(outcomes(receipt)).toEqual({ applied: [{ index: 0, node_id: ids.rust, changed: false }], skipped: [] });
    expect((await w.tree.getChildren(ids.dynomark)).map((n) => n.title)).toEqual(['Rust']);
  });

  it('Given two child folders with the title, When create_folder applies, Then the one with the lower index is named', async () => {
    const { w, ids } = await world();
    await w.tree.createFolder(ids.dynomark, 'Go');
    const second = await w.tree.createFolder(ids.dynomark, 'Go');
    const first = (await w.tree.getChildren(ids.dynomark)).find((n) => n.title === 'Go' && n.id !== second.id);
    const receipt = await applyBatch(batch({ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }), CONTEXT, w.worker());
    expect(outcomes(receipt)).toEqual({ applied: [{ index: 0, node_id: first?.id, changed: false }], skipped: [] });
  });

  it('Given only a bookmark carries the title, When create_folder applies, Then a folder is created', async () => {
    const { w, ids } = await world();
    await w.tree.createBookmark(ids.dynomark, 'Go', 'https://go.dev/');
    const receipt = await applyBatch(batch({ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }), CONTEXT, w.worker());
    expect(receipt).toMatchObject({ state: 'APPLIED', applied: [{ index: 0, changed: true }] });
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Go'] })).toBeDefined();
  });

  it('Given a child bookmark with the exact url exists, When create applies, Then it is unchanged; a url that differs only in its query is created', async () => {
    const { w, ids } = await world();
    const existing = await w.tree.createBookmark(ids.rust, 'Book', 'https://doc.rust-lang.org/book/');
    const receipt = await applyBatch(
      batch(
        { op: 'create', index: 0, parent: RUST, title: 'Book', url: 'https://doc.rust-lang.org/book/' },
        { op: 'create', index: 1, parent: RUST, title: 'Book', url: 'https://doc.rust-lang.org/book/?x=1' },
      ),
      CONTEXT,
      w.worker(),
    );
    expect(receipt).toMatchObject({
      applied: [
        { index: 0, node_id: existing.id, changed: false },
        { index: 1, changed: true },
      ],
    });
    expect(await w.tree.getChildren(ids.rust)).toHaveLength(2);
  });

  it('Given the node is already directly in the target, When move applies, Then it is applied unchanged and its failing expect is not evaluated', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(
      batch({ op: 'move', index: 0, node_id: ids.saved, to: FOLLOW_UP, expect: { parent_id: ids.rust, empty: true } }),
      CONTEXT,
      w.worker(),
    );
    expect(outcomes(receipt)).toEqual({ applied: [{ index: 0, node_id: ids.saved, changed: false }], skipped: [] });
  });

  it('Given the node is already in the graveyard, When remove applies, Then it is applied unchanged', async () => {
    const { w, ids } = await world();
    await w.tree.move(ids.saved, ids.graveyard);
    const receipt = await applyBatch(
      batch({ op: 'remove', index: 0, node_id: ids.saved, expect: { parent_id: ids.followUp } }),
      CONTEXT,
      w.worker(),
    );
    expect(outcomes(receipt)).toEqual({ applied: [{ index: 0, node_id: ids.saved, changed: false }], skipped: [] });
  });

  it('Given the cursor was lost after a batch applied, When the batch runs again from op 0, Then every op is a no-op and the tree is unchanged', async () => {
    const { w, ids } = await world();
    const filing = batch(
      { op: 'create_folder', index: 0, parent: RUST, title: 'Async' },
      {
        op: 'move',
        index: 1,
        node_id: ids.saved,
        to: { root: 'bar', names: ['Dynomark', 'Rust', 'Async'] },
        expect: { parent_id: ids.followUp },
      },
    );
    await applyBatch(filing, CONTEXT, w.worker());
    await w.storage.clearCursor();
    const tree = await w.tree.readTree();
    const again = await applyBatch(filing, CONTEXT, w.worker());
    expect(again.state === 'APPLIED' ? again.applied.map((a) => a.changed) : again.state).toEqual([false, false]);
    expect(await w.tree.readTree()).toEqual(tree);
  });
});

describe('Preconditions -- an expect clause that fails skips the op and the batch continues', () => {
  it('Given a move whose node the user moved elsewhere, When applied, Then it is skipped parent_mismatch and the next op still runs', async () => {
    const { w, ids } = await world();
    await w.tree.move(ids.saved, ids.rust);
    const receipt = await applyBatch(
      batch(
        { op: 'move', index: 0, node_id: ids.saved, to: GRAVEYARD, expect: { parent_id: ids.followUp } },
        { op: 'create_folder', index: 1, parent: DYNOMARK, title: 'Go' },
      ),
      CONTEXT,
      w.worker(),
    );
    expect(receipt).toMatchObject({
      state: 'APPLIED',
      skipped: [{ index: 0, reason: 'parent_mismatch' }],
      applied: [{ index: 1, changed: true }],
    });
    expect(await w.tree.getNode(ids.saved)).toMatchObject({ parent_id: ids.rust });
    expect(() => BatchReceiptSchema.parse(receipt)).not.toThrow();
  });

  it('Given expect.parent_path resolves to another folder than the node is in, When applied, Then it is skipped parent_mismatch', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(
      batch({ op: 'move', index: 0, node_id: ids.saved, to: RUST, expect: { parent_id: ids.followUp, parent_path: DYNOMARK } }),
      CONTEXT,
      w.worker(),
    );
    expect(outcomes(receipt)).toEqual({ applied: [], skipped: [{ index: 0, reason: 'parent_mismatch' }] });
  });

  it('Given expect.empty on a folder that now holds an item, When remove applies, Then it is skipped not_empty and the folder stays', async () => {
    const { w, ids } = await world();
    await w.tree.createBookmark(ids.rust, 'Book', 'https://doc.rust-lang.org/book/');
    const receipt = await applyBatch(
      batch({ op: 'remove', index: 0, node_id: ids.rust, expect: { parent_id: ids.dynomark, empty: true } }),
      CONTEXT,
      w.worker(),
    );
    expect(outcomes(receipt)).toEqual({ applied: [], skipped: [{ index: 0, reason: 'not_empty' }] });
    expect(await w.tree.getNode(ids.rust)).toMatchObject({ parent_id: ids.dynomark });
  });

  it('Given expect.empty on an empty folder, When remove applies, Then it moves to the graveyard', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(
      batch({ op: 'remove', index: 0, node_id: ids.rust, expect: { parent_id: ids.dynomark, empty: true } }),
      CONTEXT,
      w.worker(),
    );
    expect(receipt).toMatchObject({ applied: [{ index: 0, node_id: ids.rust, changed: true }] });
    expect(await w.tree.getNode(ids.rust)).toMatchObject({ parent_id: ids.graveyard });
  });

  it('Given the user deleted the node, When a move applies, Then it is skipped node_missing even when its target does not resolve', async () => {
    const { w, ids } = await world();
    w.tree.deleteByUser(ids.saved);
    const receipt = await applyBatch(
      batch({
        op: 'move',
        index: 0,
        node_id: ids.saved,
        to: { root: 'bar', names: ['Dynomark', 'Gone'] },
        expect: { parent_id: ids.followUp },
      }),
      CONTEXT,
      w.worker(),
    );
    expect(outcomes(receipt)).toEqual({ applied: [], skipped: [{ index: 0, reason: 'node_missing' }] });
  });
});
