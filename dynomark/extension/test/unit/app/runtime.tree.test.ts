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
