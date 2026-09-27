// world.fake.test.ts -- the fakes simulate what the extension runtime must
// survive (design, "The extension": its runtime can be terminated between any
// two events; durable extension state is exactly settings, the LocalIndex and
// the in-flight batch cursor). A tree call can fail at op N; a service worker
// can die mid-call; after a restart only the browser's own data and what was
// saved to storage remain.

import { describe, expect, it } from 'vitest';
import { BrowserRefused } from '../../../src/ports/bookmarkTree.js';
import type { BatchCursor } from '../../../src/domain/batch.js';
import { FakeBookmarkTree } from '../../fakes/FakeBookmarkTree.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { WorkerTerminated } from '../../fakes/WorkerTerminated.js';

// --- Builders ---

const CURSOR: BatchCursor = {
  batch_id: 'batch-1',
  next_index: 1,
  outcomes: [{ outcome: 'applied', index: 0, node_id: '4', changed: true }],
};

// --- Tests ---

describe('FakeBookmarkTree failure at op N', () => {
  it('Given a refusal armed at mutation 2, When three folders are created, Then only the second is refused and the tree lacks only it', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    tree.failOnMutation(2, 'refuse');
    await tree.createFolder('1', 'A');
    await expect(tree.createFolder('1', 'B')).rejects.toBeInstanceOf(BrowserRefused);
    await tree.createFolder('1', 'C');
    expect((await tree.getChildren('1')).map((n) => n.title)).toEqual(['A', 'C']);
  });

  it('Given termination armed before mutation 1, When a folder is created, Then the call dies and the browser never made the folder', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    tree.failOnMutation(1, 'terminate-before');
    await expect(tree.createFolder('1', 'A')).rejects.toBeInstanceOf(WorkerTerminated);
    expect(await tree.getChildren('1')).toEqual([]);
  });

  it('Given termination armed after mutation 1, When a node is moved, Then the call dies but the browser did move it', async () => {
    const tree = new FakeBookmarkTree({ flavor: 'chrome' });
    const node = await tree.createBookmark('1', 'Tokio', 'https://tokio.rs/');
    tree.failOnMutation(1, 'terminate-after');
    await expect(tree.move(node.id, '2')).rejects.toBeInstanceOf(WorkerTerminated);
    expect(await tree.getNode(node.id)).toMatchObject({ parent_id: '2' });
  });
});

describe('FakeExtensionWorld service-worker restart', () => {
  it('Given a worker killed mid-move, When it tries anything more, Then every port of that worker refuses and nothing it attempts lands', async () => {
    const world = new FakeExtensionWorld({ flavor: 'chrome' });
    const worker = world.worker();
    const node = await worker.tree.createBookmark('1', 'Tokio', 'https://tokio.rs/');
    world.tree.failOnMutation(1, 'terminate-after');
    await expect(worker.tree.move(node.id, '2')).rejects.toBeInstanceOf(WorkerTerminated);
    await expect(worker.storage.saveCursor(CURSOR)).rejects.toBeInstanceOf(WorkerTerminated);
    await expect(worker.tree.createFolder('1', 'Late')).rejects.toBeInstanceOf(WorkerTerminated);
    expect(() => worker.clock.now()).toThrow(WorkerTerminated);
    const next = world.restart();
    expect(await next.storage.loadCursor()).toBeUndefined();
    expect(await next.tree.getNode(node.id)).toMatchObject({ parent_id: '2' });
    expect((await next.tree.getChildren('1')).map((n) => n.title)).toEqual([]);
  });

  it('Given a cursor saved and a tree edit, When the worker restarts, Then the new worker sees both and holds a new daemon connection', async () => {
    const world = new FakeExtensionWorld({ flavor: 'chrome' });
    const old = world.worker();
    await old.storage.saveCursor(CURSOR);
    const folder = await old.tree.createFolder('1', 'Dynomark');
    const heard: string[] = [];
    old.transport.onEvent((e) => heard.push(e.event_id));
    const inFlight = old.transport.send({ v: 1, type: 'events.replay', id: 'req-1' });
    const next = world.restart();
    await expect(inFlight).rejects.toMatchObject({ reason: 'disconnected' });
    expect(await next.storage.loadCursor()).toEqual(CURSOR);
    expect(await next.tree.getNode(folder.id)).toMatchObject({ title: 'Dynomark' });
    expect(next.transport).not.toBe(old.transport);
    await world.daemon().emit({ v: 1, type: 'diff.proposed', event_id: 'evt-1', diff: DIFF });
    expect(heard).toEqual([]);
  });
});

const DIFF = { diff_id: 'diff-1', kind: 'rebuild' as const, proposed_at: 1, item_count: 0, unaccepted_count: 0 };
