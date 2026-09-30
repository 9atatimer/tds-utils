// diffs.test.ts -- the extension half of TreeDiffs (design, Behaviors rows "A
// diff is proposed", "A diff item is accepted", "An audit item may cross the
// boundary"; Non-Goals: audit is suggest-only, one accepted item at a time;
// contract v1, "Connection lifecycle" step 6: tree.snapshot immediately
// before every diff.propose, awaiting its result, so an audit compares
// against the current bar). The diff view lists diffs and their items,
// proposes, accepts one item at a time, and sets pin/lock flags.

import { describe, expect, it } from 'vitest';
import { DiffAcceptance, listDiffs, proposeDiff, readDiffPage, readOutline, setFolderFlags } from '../../../src/app/diffs.js';
import type { DiffItem, OutlineFolder, TreeDiff } from '../../../src/domain/diff.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';
import { seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const DIFF: TreeDiff = { diff_id: 'diff-2', kind: 'audit', proposed_at: 1_790_000_090_000, item_count: 1, unaccepted_count: 1 };

const ITEM: DiffItem = {
  item_id: 'item-3',
  diff_id: 'diff-2',
  action: 'add',
  description: 'Add The Rust Book to your bar folder Reading',
  operations: [{ op: 'create_folder', index: 0, parent: { root: 'bar', names: [] }, title: 'Reading' }],
  accepted_at: null,
};

const FOLDER: OutlineFolder = {
  node_id: '14',
  path: { root: 'bar', names: ['Dynomark', 'Rust'] },
  pinned: false,
  locked: false,
  item_count: 1,
};

function daemon(r: RequestMessage): ResponseMessage {
  switch (r.type) {
    case 'tree.snapshot':
      return { v: 1, type: 'tree.snapshot.result', re: r.id };
    case 'diff.propose':
      return { v: 1, type: 'diff.propose.result', re: r.id, diff: { ...DIFF, kind: r.kind } };
    case 'diff.list':
      return { v: 1, type: 'diff.list.result', re: r.id, diffs: [DIFF], next_cursor: r.cursor === undefined ? 'p2' : null };
    case 'diff.page':
      return { v: 1, type: 'diff.page.result', re: r.id, diff: DIFF, items: [ITEM], next_cursor: null };
    case 'diff.accept':
      return { v: 1, type: 'diff.accept.result', re: r.id, item_id: r.item_id, accepted_at: 1_790_000_125_000, batch_id: 'batch-104' };
    case 'outline.get':
      return { v: 1, type: 'outline.get.result', re: r.id, outline: [FOLDER], next_cursor: null };
    case 'folder.flags.set':
      return {
        v: 1,
        type: 'folder.flags.set.result',
        re: r.id,
        folder: { ...FOLDER, pinned: r.pinned ?? FOLDER.pinned, locked: r.locked ?? FOLDER.locked },
      };
    default:
      throw new Error(`unexpected ${r.type}`);
  }
}

async function deps(options: { readonly manual?: boolean } = {}) {
  const tree = new FakeBookmarkTree({ flavor: 'chrome' });
  await seedOwnedTree(tree);
  const transport = new FakeTransport();
  if (options.manual !== true) transport.autoAnswer(daemon);
  return { transport, ids: new SequentialIdSource(), tree, clock: new FakeClock(1_790_000_000_000) };
}

// --- Tests ---

describe('proposeDiff(kind, { transport, ids, tree, clock })', () => {
  it('Given an audit, When proposed, Then tree.snapshot goes first and diff.propose waits for its result', async () => {
    const d = await deps({ manual: true });
    const proposed = proposeDiff('audit', d);
    const snapshot = await d.transport.daemon.nextRequest();
    expect(snapshot.type).toBe('tree.snapshot');
    expect(d.transport.sent.map((r) => r.type)).toEqual(['tree.snapshot']);
    await d.transport.daemon.answer(daemon(snapshot));
    const propose = await d.transport.daemon.nextRequest();
    expect(propose).toMatchObject({ type: 'diff.propose', kind: 'audit' });
    await d.transport.daemon.answer(daemon(propose));
    expect(await proposed).toEqual(DIFF);
  });

  it('Given a rebuild, When proposed, Then the diff header of kind rebuild comes back and no batch is involved', async () => {
    const d = await deps();
    expect((await proposeDiff('rebuild', d)).kind).toBe('rebuild');
    expect(d.transport.sent.map((r) => r.type)).toEqual(['tree.snapshot', 'diff.propose']);
  });
});

describe('listDiffs and readDiffPage -- the diff view reads, page by page', () => {
  it('Given two pages of diffs, When listed from a cursor, Then diff.list carries it and the next cursor comes back', async () => {
    const d = await deps();
    expect(await listDiffs(undefined, d)).toEqual({ diffs: [DIFF], next_cursor: 'p2' });
    expect(await listDiffs('p2', d)).toEqual({ diffs: [DIFF], next_cursor: null });
    expect(d.transport.sent.map((r) => (r.type === 'diff.list' ? (r.cursor ?? '-') : r.type))).toEqual(['-', 'p2']);
  });

  it('Given a diff, When its page is read, Then its items come back, each with accepted_at (null: proposed)', async () => {
    const d = await deps();
    expect(await readDiffPage('diff-2', undefined, d)).toEqual({ diff: DIFF, items: [ITEM], next_cursor: null });
    expect(d.transport.sent[0]).toMatchObject({ type: 'diff.page', diff_id: 'diff-2' });
  });
});

describe('DiffAcceptance -- one item at a time', () => {
  it('Given an item, When accepted, Then diff.accept names only its id and the recorded accepted_at and batch come back', async () => {
    const d = await deps();
    expect(await new DiffAcceptance().accept('item-3', d)).toEqual({
      item_id: 'item-3',
      accepted_at: 1_790_000_125_000,
      batch_id: 'batch-104',
    });
    expect(d.transport.sent).toEqual([expect.objectContaining({ type: 'diff.accept', item_id: 'item-3' })]);
  });

  it('Given an acceptance in flight, When another item is accepted, Then it is refused and never sent', async () => {
    const d = await deps({ manual: true });
    const acceptance = new DiffAcceptance();
    const first = acceptance.accept('item-3', d);
    await expect(acceptance.accept('item-4', d)).rejects.toThrow(/one diff item at a time/);
    const request = await d.transport.daemon.nextRequest();
    await d.transport.daemon.answer(daemon(request));
    await first;
    expect(d.transport.sent.map((r) => (r.type === 'diff.accept' ? r.item_id : r.type))).toEqual(['item-3']);
  });

  it('Given the first acceptance was answered, When the next is accepted, Then it is sent', async () => {
    const d = await deps();
    const acceptance = new DiffAcceptance();
    await acceptance.accept('item-3', d);
    await acceptance.accept('item-4', d);
    expect(d.transport.sent.map((r) => (r.type === 'diff.accept' ? r.item_id : r.type))).toEqual(['item-3', 'item-4']);
  });
});

describe('readOutline and setFolderFlags -- pin and lock', () => {
  it('Given the owned outline, When read, Then its folders come back with their flags', async () => {
    const d = await deps();
    expect(await readOutline(undefined, d)).toEqual({ folders: [FOLDER], next_cursor: null });
  });

  it('Given a folder, When pinned, Then folder.flags.set names its node id and path and only the flag changed', async () => {
    const d = await deps();
    expect(await setFolderFlags(FOLDER, { pinned: true }, d)).toEqual({ ...FOLDER, pinned: true });
    const [sent] = d.transport.sent;
    expect(sent).toEqual(expect.objectContaining({ type: 'folder.flags.set', node_id: '14', path: FOLDER.path, pinned: true }));
    expect(sent !== undefined && 'locked' in sent).toBe(false);
  });

  it('Given no flag to change, When set, Then it is refused and nothing is sent', async () => {
    const d = await deps();
    await expect(setFolderFlags(FOLDER, {}, d)).rejects.toThrow(/flag/);
    expect(d.transport.sent).toEqual([]);
  });
});
