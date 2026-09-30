// runtime.diffs.test.ts -- what the diff view asks the background for
// (design, "Diffs": propose_diff of kind audit or rebuild, nothing applied
// until a DiffItem is accepted, each acceptance its own batch; Transport
// contract: REJECTED and PARTIAL surface in the diff view). Proposing sends a
// fresh tree.snapshot first; accepting is one item at a time; the pin and lock
// controls set folder flags. Daemon refusals come back with their code.

import { describe, expect, it } from 'vitest';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { scriptDaemon, sentOf, sentTypes, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

const DIFF = { diff_id: 'diff-2', kind: 'audit' as const, proposed_at: 5, item_count: 1, unaccepted_count: 0 };
const FOLDER = { node_id: '16', path: { root: 'bar' as const, names: ['Dynomark', 'Rust'] }, pinned: false, locked: false, item_count: 1 };

function answers(r: RequestMessage): ResponseMessage | undefined {
  switch (r.type) {
    case 'diff.propose':
      return { v: 1, type: 'diff.propose.result', re: r.id, diff: DIFF };
    case 'diff.list':
      return { v: 1, type: 'diff.list.result', re: r.id, diffs: [DIFF], next_cursor: null };
    case 'diff.page':
      return {
        v: 1,
        type: 'diff.page.result',
        re: r.id,
        diff: DIFF,
        items: [
          {
            item_id: 'item-4',
            diff_id: 'diff-2',
            action: 'move',
            description: 'Move Rust under Code',
            operations: [
              {
                op: 'move',
                index: 0,
                node_id: '16',
                to: { root: 'bar', names: ['Dynomark', 'Code'] },
                expect: { parent_id: '11' },
              },
            ],
            accepted_at: 9,
            batch_id: 'batch-106',
            batch_state: 'PARTIAL',
          },
        ],
        next_cursor: null,
      };
    case 'diff.accept':
      return r.item_id === 'item-conflict'
        ? { v: 1, type: 'error', re: r.id, code: 'writer_conflict', message: 'marker of host work-laptop present' }
        : { v: 1, type: 'diff.accept.result', re: r.id, item_id: r.item_id, accepted_at: 10, batch_id: 'batch-107' };
    case 'outline.get':
      return { v: 1, type: 'outline.get.result', re: r.id, outline: [FOLDER], next_cursor: null };
    case 'folder.flags.set':
      return { v: 1, type: 'folder.flags.set.result', re: r.id, folder: { ...FOLDER, locked: r.locked ?? false } };
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

describe('Diff view -- propose, list, read', () => {
  it('Given the diff view, When an audit is proposed, Then a fresh tree.snapshot precedes diff.propose and the header comes back', async () => {
    const { w, runtime } = await setup();
    const before = w.connection().sent.length;
    expect(await runtime.page({ kind: 'diff.propose', diff_kind: 'audit' })).toEqual({ ok: true, kind: 'diff.propose', diff: DIFF });
    expect(sentTypes(w).slice(before)).toEqual(['tree.snapshot', 'diff.propose']);
  });

  it('Given diffs, When listed and one is opened, Then each item shows its accepted batch and that batch state', async () => {
    const { runtime } = await setup();
    expect(await runtime.page({ kind: 'diff.list' })).toEqual({ ok: true, kind: 'diff.list', diffs: [DIFF], next_cursor: null });
    const page = await runtime.page({ kind: 'diff.page', diff_id: 'diff-2' });
    expect(page).toMatchObject({
      ok: true,
      kind: 'diff.page',
      items: [{ item_id: 'item-4', batch_id: 'batch-106', batch_state: 'PARTIAL' }],
    });
  });
});

describe('Diff view -- accept one item, pin and lock', () => {
  it('Given an item, When accepted, Then diff.accept names it and the batch it produced comes back', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'diff.accept', item_id: 'item-3' })).toEqual({
      ok: true,
      kind: 'diff.accept',
      item_id: 'item-3',
      accepted_at: 10,
      batch_id: 'batch-107',
    });
    expect(sentOf(w, 'diff.accept').map((r) => r.item_id)).toEqual(['item-3']);
  });

  it('Given two accepts at once, When both are pressed, Then only the first is sent and the second is refused', async () => {
    const { w, runtime } = await setup();
    const [first, second] = await Promise.all([
      runtime.page({ kind: 'diff.accept', item_id: 'item-3' }),
      runtime.page({ kind: 'diff.accept', item_id: 'item-5' }),
    ]);
    expect(first).toMatchObject({ ok: true });
    expect(second).toMatchObject({ ok: false });
    expect(sentOf(w, 'diff.accept').map((r) => r.item_id)).toEqual(['item-3']);
  });

  it('Given a writer in conflict, When an item is accepted, Then the page gets ok false with code writer_conflict', async () => {
    const { runtime } = await setup();
    expect(await runtime.page({ kind: 'diff.accept', item_id: 'item-conflict' })).toMatchObject({ ok: false, code: 'writer_conflict' });
  });

  it('Given the outline, When a folder is locked, Then folder.flags.set carries its node id, path and the lock', async () => {
    const { w, runtime } = await setup();
    expect(await runtime.page({ kind: 'outline' })).toEqual({ ok: true, kind: 'outline', folders: [FOLDER], next_cursor: null });
    const page = await runtime.page({ kind: 'folder.flags', node_id: '16', path: FOLDER.path, locked: true });
    expect(page).toEqual({ ok: true, kind: 'folder.flags', folder: { ...FOLDER, locked: true } });
    expect(sentOf(w, 'folder.flags.set')[0]).toMatchObject({ node_id: '16', path: FOLDER.path, locked: true });
  });
});
