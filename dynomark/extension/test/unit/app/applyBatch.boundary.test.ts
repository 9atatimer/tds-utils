// applyBatch.boundary.test.ts -- task-024 row 12 and design Goal 8
// (ownership boundary), extension side. Contract v2, "Write batches",
// Boundary: before the first op, every op is checked against owned_roots;
// a batch with diff_item_id may also stay inside the accepted item's scope
// (issue #423: no longer exempt). The check is syntactic on paths
// (same RootKey, owned names a prefix); the owned-root create_folder is
// admitted; a move or remove of an existing node needs an owned root among
// its ancestors; a node missing at check time passes. Any failure is
// REJECTED boundary and nothing is touched. Op indices not 0..n-1 are
// REJECTED invalid; another host's writer marker is REJECTED writer_conflict.

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

function batch(operations: WriteBatch['operations'], diff_item_id?: string, scope?: WriteBatch['scope']): WriteBatch {
  return {
    batch_id: 'batch-b',
    operations,
    ...(diff_item_id === undefined ? {} : { diff_item_id }),
    ...(scope === undefined ? {} : { scope }),
  };
}

const BAR = { root: 'bar' as const, names: [] };

async function expectRejectedUntouched(w: FakeExtensionWorld, b: WriteBatch, reason: string): Promise<void> {
  const before = await w.tree.readTree();
  const receipt = await applyBatch(b, CONTEXT, w.worker());
  expect(receipt).toMatchObject({ state: 'REJECTED', reason, pre_batch: true });
  expect(receipt.snapshot).toEqual({ ...before, taken_at: w.clock.now() });
  expect(() => BatchReceiptSchema.parse(receipt)).not.toThrow();
  expect(await w.tree.readTree()).toEqual(before);
  expect(await w.storage.loadCursor()).toBeUndefined();
}

// --- Tests ---

describe('Ownership boundary in the extension -- applyBatch refuses a batch outside OwnedRoots before its first op', () => {
  it('Given a create_folder on the bookmarks bar itself, When applied, Then the batch is REJECTED boundary and nothing is touched', async () => {
    const { w } = await world();
    await expectRejectedUntouched(w, batch([{ op: 'create_folder', index: 0, parent: BAR, title: 'Loot' }]), 'boundary');
  });

  it('Given an admissible op followed by one outside the roots, When applied, Then the whole batch is REJECTED before the first op runs', async () => {
    const { w } = await world();
    await expectRejectedUntouched(
      w,
      batch([
        { op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' },
        { op: 'create', index: 1, parent: BAR, title: 'Ad', url: 'https://ad.example/' },
      ]),
      'boundary',
    );
  });

  it('Given a move to a folder outside the roots, When applied, Then it is REJECTED boundary', async () => {
    const { w, ids } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'move', index: 0, node_id: ids.saved, to: BAR, expect: { parent_id: ids.followUp } }]),
      'boundary',
    );
  });

  it("Given a move of the user's own bookmark into Dynomark, When applied, Then it is REJECTED boundary (no owned root among its ancestors)", async () => {
    const { w, ids } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'move', index: 0, node_id: ids.usersOwn, to: RUST, expect: { parent_id: ids.bar } }]),
      'boundary',
    );
  });

  it("Given a remove of the user's own bookmark, When applied, Then it is REJECTED boundary", async () => {
    const { w, ids } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'remove', index: 0, node_id: ids.usersOwn, expect: { parent_id: ids.bar } }]),
      'boundary',
    );
  });

  it('Given a folder titled Dynomark under another root key, When a create targets it, Then it is REJECTED (the check is syntactic on paths)', async () => {
    const { w, ids } = await world();
    const other = (await w.tree.readTree()).root_ids.other;
    await w.tree.createFolder(other, 'Dynomark');
    expect(ids.dynomark).toBeDefined();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'create_folder', index: 0, parent: { root: 'other', names: ['Dynomark'] }, title: 'X' }]),
      'boundary',
    );
  });

  it("Given an accepted DiffItem's batch, When an op takes a node from a folder its scope does not name, Then the batch is REJECTED boundary: a diff item is no longer exempt (issue #423)", async () => {
    const { w, ids } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'move', index: 0, node_id: ids.usersOwn, to: RUST, expect: { parent_id: ids.bar } }], 'item-7', [RUST]),
      'boundary',
    );
  });

  it("Given an accepted DiffItem's batch, When an op targets a folder its scope does not name, Then the batch is REJECTED boundary", async () => {
    const { w } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'create_folder', index: 0, parent: { root: 'other', names: [] }, title: 'Loot' }], 'item-7', [BAR]),
      'boundary',
    );
  });

  it("Given an accepted DiffItem's batch, When an op targets a folder under a scope path but not the path itself, Then it is REJECTED boundary (a scope path admits only itself)", async () => {
    const { w } = await world();
    await expectRejectedUntouched(
      w,
      batch([{ op: 'create_folder', index: 0, parent: { root: 'bar', names: ['Reading'] }, title: 'Deeper' }], 'item-7', [BAR]),
      'boundary',
    );
  });

  it('Given op indices that are not 0..n-1, When applied, Then it is REJECTED invalid', async () => {
    const { w } = await world();
    await expectRejectedUntouched(
      w,
      batch([
        { op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' },
        { op: 'create_folder', index: 2, parent: DYNOMARK, title: 'Zig' },
      ]),
      'invalid',
    );
  });

  it("Given another host's writer marker in Dynomark, When a batch arrives, Then it is REJECTED writer_conflict", async () => {
    const { w, ids } = await world();
    await w.tree.createFolder(ids.dynomark, 'dynomark-writer:studio');
    await expectRejectedUntouched(w, batch([{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }]), 'writer_conflict');
  });
});

describe('Ownership boundary -- what is admitted', () => {
  it("Given a fresh tree, When a batch creates the owned roots and this host's writer marker, Then the owned-root create_folder is admitted and applied", async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const receipt = await applyBatch(
      batch([
        { op: 'create_folder', index: 0, parent: BAR, title: 'Dynomark' },
        { op: 'create_folder', index: 1, parent: BAR, title: 'Graveyard' },
        { op: 'create_folder', index: 2, parent: DYNOMARK, title: 'dynomark-writer:mbp' },
      ]),
      CONTEXT,
      w.worker(),
    );
    expect(receipt.state).toBe('APPLIED');
    expect(await w.worker().tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'dynomark-writer:mbp'] })).toBeDefined();
  });

  it('Given a move from Follow Up and a remove of a node deep in Dynomark, When applied, Then both are admitted (an owned root is an ancestor)', async () => {
    const { w, ids } = await world();
    const deep = await w.tree.createBookmark(ids.rust, 'Book', 'https://doc.rust-lang.org/book/');
    const receipt = await applyBatch(
      batch([
        { op: 'move', index: 0, node_id: ids.saved, to: RUST, expect: { parent_id: ids.followUp, parent_path: FOLLOW_UP } },
        { op: 'remove', index: 1, node_id: deep.id, expect: { parent_id: ids.rust } },
      ]),
      CONTEXT,
      w.worker(),
    );
    expect(receipt).toMatchObject({
      state: 'APPLIED',
      applied: [
        { index: 0, changed: true },
        { index: 1, changed: true },
      ],
    });
  });

  it('Given a move of a node that no longer exists, When applied, Then it passes the boundary and is skipped node_missing', async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(
      batch([{ op: 'move', index: 0, node_id: '999', to: RUST, expect: { parent_id: ids.bar } }]),
      CONTEXT,
      w.worker(),
    );
    expect(receipt).toMatchObject({ state: 'APPLIED', skipped: [{ index: 0, reason: 'node_missing' }] });
  });

  it("Given an accepted DiffItem's batch whose scope names the user's bar and Rust, When it moves the user's own bookmark from the bar into Rust, Then it is admitted and applied", async () => {
    const { w, ids } = await world();
    const receipt = await applyBatch(
      batch([{ op: 'move', index: 0, node_id: ids.usersOwn, to: RUST, expect: { parent_id: ids.bar, parent_path: BAR } }], 'item-7', [
        RUST,
        BAR,
      ]),
      CONTEXT,
      w.worker(),
    );
    expect(receipt.state).toBe('APPLIED');
    expect(await w.tree.getNode(ids.usersOwn)).toMatchObject({ parent_id: ids.rust });
  });

  it('Given an accepted DiffItem whose batch stays inside the owned roots, When applied, Then it is admitted though its scope names other folders', async () => {
    const { w } = await world();
    const receipt = await applyBatch(
      batch([{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }], 'item-8', [BAR]),
      CONTEXT,
      w.worker(),
    );
    expect(receipt.state).toBe('APPLIED');
  });

  it('Given the daemon reported a writer conflict, When a batch arrives with no marker in the tree, Then it is still REJECTED writer_conflict', async () => {
    const { w } = await world();
    const before = await w.tree.readTree();
    const receipt = await applyBatch(
      batch([{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }]),
      { ...CONTEXT, writer_conflict: true },
      w.worker(),
    );
    expect(receipt).toMatchObject({ state: 'REJECTED', reason: 'writer_conflict' });
    expect(await w.tree.readTree()).toEqual(before);
    expect(await w.storage.loadCursor()).toBeUndefined();
  });

  it("Given this host's own writer marker in Dynomark, When a batch arrives, Then it is applied", async () => {
    const { w, ids } = await world();
    await w.tree.createFolder(ids.dynomark, 'dynomark-writer:mbp');
    expect((await applyBatch(batch([{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }]), CONTEXT, w.worker())).state).toBe(
      'APPLIED',
    );
  });
});
