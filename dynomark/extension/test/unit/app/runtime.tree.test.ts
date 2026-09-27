// runtime.tree.test.ts -- bookmark events in the background composition
// (design, "The extension": Watch Follow Up, Capture from the open tab,
// Record feedback; contract v1 README, "Connection lifecycle", step 6). A
// bookmark created in, or moved into, Follow Up is captured from an open tab
// (unless the capture setting is off) and ingested; a move between owned
// folders is reported as move.observed with its origin; changes under the
// owned roots send one debounced tree.snapshot; a batch.offer event is
// applied and answered.

import { describe, expect, it } from 'vitest';
import { SNAPSHOT_DEBOUNCE_MS } from '../../../src/app/runtime.js';
import { RECONNECT_BACKOFF } from '../../../src/domain/backoff.js';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { BookmarkEvent } from '../../../src/ports/bookmarkEvents.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { DYNOMARK, RUST, seedOwnedTree, type Seeded } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

async function setup(): Promise<{ w: FakeExtensionWorld; ids: Seeded; runtime: ExtensionRuntime }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w);
  const ids = await seedOwnedTree(w.tree);
  const runtime = await startRuntime(w);
  return { w, ids, runtime };
}

async function deliver(runtime: ExtensionRuntime, event: BookmarkEvent): Promise<void> {
  runtime.onBookmarkEvent(event);
  await runtime.idle();
}

async function created(w: FakeExtensionWorld, runtime: ExtensionRuntime, parent: string, title: string, url: string) {
  const node = await w.tree.createBookmark(parent, title, url);
  await deliver(runtime, { kind: 'created', node });
  return node;
}

async function moved(w: FakeExtensionWorld, runtime: ExtensionRuntime, id: string, to: string): Promise<void> {
  const old_parent_id = (await w.tree.getNode(id))?.parent_id ?? '';
  await w.tree.move(id, to);
  await deliver(runtime, { kind: 'moved', node_id: id, parent_id: to, old_parent_id });
}

const PAGE = { title: 'Serde', text: 'Serde is a framework for serializing and deserializing Rust data structures.' };

// --- Tests ---

describe('Watch Follow Up -- a save is captured and ingested', () => {
  it('Given a tab showing the URL, When a bookmark is created in Follow Up, Then ingest carries a tab capture of that page', async () => {
    const { w, ids, runtime } = await setup();
    w.tabs.open('https://serde.rs/', PAGE);
    const node = await created(w, runtime, ids.followUp, 'Serde', 'https://serde.rs/');
    const ingest = sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id);
    expect(ingest).toMatchObject({ backfill: false, capture: { source: 'tab', text: PAGE.text, title: 'Serde' } });
    expect(ingest?.bookmark).toMatchObject({ url: 'https://serde.rs/', path: { root: 'bar', names: ['Follow Up'] } });
  });

  it('Given no tab shows the URL, When a bookmark is created in Follow Up, Then ingest carries source none', async () => {
    const { w, ids, runtime } = await setup();
    const node = await created(w, runtime, ids.followUp, 'Serde', 'https://serde.rs/');
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)?.capture).toEqual({ source: 'none', text: '' });
  });

  it('Given the capture setting is off, When a bookmark is created in Follow Up with a tab open, Then ingest carries source none', async () => {
    const { w, ids, runtime } = await setup();
    expect(await runtime.page({ kind: 'settings.set', capture_from_tab: false })).toMatchObject({ ok: true });
    w.tabs.open('https://serde.rs/', PAGE);
    const node = await created(w, runtime, ids.followUp, 'Serde', 'https://serde.rs/');
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)?.capture).toEqual({ source: 'none', text: '' });
    expect((await w.storage.loadSettings())?.capture_from_tab).toBe(false);
  });

  it('Given a bookmark of the user elsewhere, When it is moved into Follow Up, Then it is ingested', async () => {
    const { w, ids, runtime } = await setup();
    await moved(w, runtime, ids.usersOwn, ids.followUp);
    expect(sentOf(w, 'ingest').map((r) => r.bookmark.node_id)).toContain(ids.usersOwn);
  });

  it('Given a bookmark created outside Follow Up, or a folder created in it, When seen, Then nothing is ingested', async () => {
    const { w, ids, runtime } = await setup();
    const before = sentOf(w, 'ingest').length;
    await created(w, runtime, ids.bar, 'Mail 2', 'https://mail2.example/');
    const folder = await w.tree.createFolder(ids.followUp, 'Sub');
    await deliver(runtime, { kind: 'created', node: folder });
    expect(sentOf(w, 'ingest')).toHaveLength(before);
  });
});

describe('Record feedback -- owned moves are reported with their origin', () => {
  it('Given a user moves a bookmark between owned folders, When seen, Then move.observed reports it with origin user', async () => {
    const { w, ids, runtime } = await setup();
    await moved(w, runtime, ids.saved, ids.rust);
    expect(sentOf(w, 'move.observed').at(-1)?.move).toMatchObject({
      node_id: ids.saved,
      from: { root: 'bar', names: ['Follow Up'] },
      to: RUST,
      origin: 'user',
    });
  });

  it('Given a move out of the owned roots, When seen, Then nothing is reported', async () => {
    const { w, ids, runtime } = await setup();
    await moved(w, runtime, ids.saved, ids.bar);
    expect(sentOf(w, 'move.observed')).toEqual([]);
  });
});

describe('Snapshots -- changes under the owned roots are debounced into one tree.snapshot', () => {
  it('Given three changes under the owned roots in a burst, When the debounce passes, Then exactly one tree.snapshot follows, of the tree as it is then', async () => {
    const { w, ids, runtime } = await setup();
    const before = sentOf(w, 'tree.snapshot').length;
    await moved(w, runtime, ids.saved, ids.rust);
    await deliver(runtime, { kind: 'changed', node_id: ids.rust });
    await deliver(runtime, { kind: 'reordered', folder_id: ids.dynomark });
    await w.timer().advance(SNAPSHOT_DEBOUNCE_MS - 1);
    expect(sentOf(w, 'tree.snapshot')).toHaveLength(before);
    await w.timer().advance(1);
    await runtime.idle();
    const snapshots = sentOf(w, 'tree.snapshot');
    expect(snapshots).toHaveLength(before + 1);
    expect(snapshots.at(-1)?.snapshot.nodes.find((n) => n.id === ids.saved)?.parent_id).toBe(ids.rust);
  });

  it('Given changes outside the owned roots only, When the debounce passes, Then no tree.snapshot is sent', async () => {
    const { w, ids, runtime } = await setup();
    const before = sentOf(w, 'tree.snapshot').length;
    await deliver(runtime, { kind: 'changed', node_id: ids.usersOwn });
    await deliver(runtime, { kind: 'removed', node_id: 'gone', parent_id: ids.bar });
    await w.timer().advance(SNAPSHOT_DEBOUNCE_MS * 2);
    await runtime.idle();
    expect(sentOf(w, 'tree.snapshot')).toHaveLength(before);
  });

  it('Given a removal inside an owned folder, When the debounce passes, Then a tree.snapshot is sent', async () => {
    const { w, ids, runtime } = await setup();
    const before = sentOf(w, 'tree.snapshot').length;
    await deliver(runtime, { kind: 'removed', node_id: 'gone', parent_id: ids.graveyard });
    await w.timer().advance(SNAPSHOT_DEBOUNCE_MS);
    await runtime.idle();
    expect(sentOf(w, 'tree.snapshot')).toHaveLength(before + 1);
  });
});

describe('Batch offers -- a batch.offer event is applied and answered', () => {
  it('Given a batch.offer moving the save into a new folder, When it arrives, Then the tree changes, the receipt is APPLIED and the move is origin extension', async () => {
    const { w, ids, runtime } = await setup();
    const offer = {
      v: 1 as const,
      type: 'batch.offer' as const,
      event_id: 'evt-offer-1',
      batch: {
        batch_id: 'batch-1',
        operations: [
          { op: 'create_folder' as const, index: 0, parent: DYNOMARK, title: 'Serde' },
          {
            op: 'move' as const,
            index: 1,
            node_id: ids.saved,
            to: { root: 'bar' as const, names: ['Dynomark', 'Serde'] },
            expect: { parent_id: ids.followUp },
          },
        ],
      },
    };
    await w.daemon().emit(offer);
    await runtime.idle();
    const serde = await w.tree.resolveFolder({ root: 'bar', names: ['Dynomark', 'Serde'] });
    expect((await w.tree.getNode(ids.saved))?.parent_id).toBe(serde);
    expect(sentOf(w, 'batch.receipt').at(-1)?.receipt).toMatchObject({ state: 'APPLIED', batch_id: 'batch-1' });
    await deliver(runtime, { kind: 'moved', node_id: ids.saved, parent_id: serde ?? '', old_parent_id: ids.followUp });
    expect(sentOf(w, 'move.observed').at(-1)?.move.origin).toBe('extension');
  });
});

describe('A batch receipt answered with a retryable code on a live link', () => {
  it('Given the daemon answers the first receipt internal and stays up, When the backoff passes, Then the extension asks for a replay and answers the re-offered batch from its cursor', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const offer = {
      v: 1 as const,
      type: 'batch.offer' as const,
      event_id: 'evt-go',
      batch: { batch_id: 'batch-go', operations: [{ op: 'create_folder' as const, index: 0, parent: DYNOMARK, title: 'Go' }] },
    };
    let receipts = 0;
    let replays = 0;
    scriptDaemon(w, {}, (r) => {
      if (r.type === 'batch.receipt' && (receipts += 1) === 1)
        return { v: 1, type: 'error', re: r.id, code: 'internal', message: 'database is locked' };
      if (r.type === 'events.replay' && (replays += 1) > 1) void w.daemon().emit(offer);
      return undefined;
    });
    await seedOwnedTree(w.tree);
    const runtime = await startRuntime(w);

    await w.daemon().emit(offer);
    await runtime.idle();
    expect(sentOf(w, 'batch.receipt')).toHaveLength(1);
    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();

    expect(sentOf(w, 'events.replay')).toHaveLength(2);
    expect(sentOf(w, 'batch.receipt').map((r) => r.receipt.batch_id)).toEqual(['batch-go', 'batch-go']);
    expect(await w.storage.loadCursor()).toBeUndefined();
  });
});

describe('An ingest answered with a retryable code on a live link', () => {
  const SERDE_URL = 'https://serde.rs/';

  /** A runtime whose daemon answers the first ingest of SERDE_URL `busy` and every later one normally. */
  async function busyOnce(): Promise<{ w: FakeExtensionWorld; ids: Seeded; runtime: ExtensionRuntime }> {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let answered = 0;
    scriptDaemon(w, {}, (r) => {
      if (r.type === 'ingest' && r.bookmark.url === SERDE_URL && (answered += 1) === 1)
        return { v: 1, type: 'error', re: r.id, code: 'busy', message: 'model loading' };
      return undefined;
    });
    const ids = await seedOwnedTree(w.tree);
    return { w, ids, runtime: await startRuntime(w) };
  }

  it('Given the daemon answers a new save busy and the link stays up, When the backoff passes, Then the identical frame is sent again with no reconnect and no recapture', async () => {
    const { w, ids, runtime } = await busyOnce();
    w.tabs.open(SERDE_URL, PAGE);
    const node = await created(w, runtime, ids.followUp, 'Serde', SERDE_URL);
    w.tabs.open(SERDE_URL, { ...PAGE, text: 'The page changed after the save.' });
    const hellos = sentOf(w, 'hello').length;

    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();

    const ingests = sentOf(w, 'ingest').filter((r) => r.bookmark.node_id === node.id);
    expect(ingests).toHaveLength(2);
    expect(ingests[1]).toEqual(ingests[0]);
    expect(sentOf(w, 'hello')).toHaveLength(hellos);
    await w.timer().advance(10 * RECONNECT_BACKOFF.max_ms);
    await runtime.idle();
    expect(sentOf(w, 'ingest').filter((r) => r.bookmark.node_id === node.id)).toHaveLength(2);
  });

  it('Given a busy save was resubmitted by a later event and answered, When the backoff passes, Then the pending retry sends nothing more', async () => {
    const { w, ids, runtime } = await busyOnce();
    const node = await created(w, runtime, ids.followUp, 'Serde', SERDE_URL);
    await deliver(runtime, { kind: 'created', node });
    expect(sentOf(w, 'ingest').filter((r) => r.bookmark.node_id === node.id)).toHaveLength(2);

    await w.timer().advance(10 * RECONNECT_BACKOFF.max_ms);
    await runtime.idle();

    expect(sentOf(w, 'ingest').filter((r) => r.bookmark.node_id === node.id)).toHaveLength(2);
  });
});

describe('Move origin -- only the moves the extension itself issued are origin extension', () => {
  const SERDE = { root: 'bar' as const, names: ['Dynomark', 'Serde'] };

  it('Given the open batch moved the save and its receipt failed, When the user then moves the save elsewhere, Then move.observed carries origin user', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let receipts = 0;
    scriptDaemon(w, {}, (r) =>
      r.type === 'batch.receipt' && (receipts += 1) === 1
        ? { v: 1, type: 'error', re: r.id, code: 'internal', message: 'database is locked' }
        : undefined,
    );
    const ids = await seedOwnedTree(w.tree);
    const runtime = await startRuntime(w);
    await w.daemon().emit({
      v: 1,
      type: 'batch.offer',
      event_id: 'evt-serde',
      batch: {
        batch_id: 'batch-serde',
        operations: [
          { op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Serde' },
          { op: 'move', index: 1, node_id: ids.saved, to: SERDE, expect: { parent_id: ids.followUp } },
        ],
      },
    });
    await runtime.idle();
    const serde = (await w.tree.resolveFolder(SERDE)) ?? '';
    await deliver(runtime, { kind: 'moved', node_id: ids.saved, parent_id: serde, old_parent_id: ids.followUp });
    expect(sentOf(w, 'move.observed').at(-1)?.move.origin).toBe('extension');

    await moved(w, runtime, ids.saved, ids.rust);
    expect(sentOf(w, 'move.observed').at(-1)?.move).toMatchObject({ node_id: ids.saved, from: SERDE, to: RUST, origin: 'user' });
  });

  it('Given one batch moves the same node twice, When the browser reports both moves after the batch closed, Then both are origin extension', async () => {
    const { w, ids, runtime } = await setup();
    await w.daemon().emit({
      v: 1,
      type: 'batch.offer',
      event_id: 'evt-twice',
      batch: {
        batch_id: 'batch-twice',
        operations: [
          { op: 'move', index: 0, node_id: ids.saved, to: RUST, expect: { parent_id: ids.followUp } },
          { op: 'move', index: 1, node_id: ids.saved, to: DYNOMARK, expect: { parent_id: ids.rust } },
        ],
      },
    });
    await runtime.idle();
    expect((await w.tree.getNode(ids.saved))?.parent_id).toBe(ids.dynomark);
    await deliver(runtime, { kind: 'moved', node_id: ids.saved, parent_id: ids.rust, old_parent_id: ids.followUp });
    await deliver(runtime, { kind: 'moved', node_id: ids.saved, parent_id: ids.dynomark, old_parent_id: ids.rust });
    expect(sentOf(w, 'move.observed').map((r) => r.move.origin)).toEqual(['extension', 'extension']);
  });

  it('Given the browser refused a move the batch issued, When the user later makes that same move, Then move.observed carries origin user', async () => {
    const { w, ids, runtime } = await setup();
    const go = await w.tree.createFolder(ids.dynomark, 'Go');
    const inner = await w.tree.createFolder(go.id, 'Inner');
    await w.daemon().emit({
      v: 1,
      type: 'batch.offer',
      event_id: 'evt-cycle',
      batch: {
        batch_id: 'batch-cycle',
        operations: [
          {
            op: 'move',
            index: 0,
            node_id: go.id,
            to: { root: 'bar', names: ['Dynomark', 'Go', 'Inner'] },
            expect: { parent_id: ids.dynomark },
          },
        ],
      },
    });
    await runtime.idle();
    expect((await w.tree.getNode(go.id))?.parent_id).toBe(ids.dynomark);
    expect(sentOf(w, 'batch.receipt').at(-1)?.receipt.batch_id).toBe('batch-cycle');

    await moved(w, runtime, inner.id, ids.dynomark);
    await moved(w, runtime, go.id, inner.id);
    expect(sentOf(w, 'move.observed').at(-1)?.move).toMatchObject({ node_id: go.id, origin: 'user' });
  });
});
