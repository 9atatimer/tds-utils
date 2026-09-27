// runtime.capture.test.ts -- background-tab capture in the background
// composition (design, Future Considerations "Background-tab capture (MVP)":
// a third ContentSourcePort adapter on the writer's extension, behind a
// setting; task-031: default on). A save no tab shows is opened in a
// background tab on the writer host; a reader host, or the setting off, leaves
// it to the daemon's fetch. The settings page toggles and keeps the setting.

import { describe, expect, it } from 'vitest';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import { RECONNECT_BACKOFF } from '../../../src/domain/backoff.js';
import type { HostRole } from '../../../src/domain/roles.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { seedOwnedTree, type Seeded } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

const URL = 'https://news.example/paywalled/story';
const PAGE = { title: 'Story', text: 'Full text visible only when signed in.' };

async function setup(role: HostRole = 'writer'): Promise<{ w: FakeExtensionWorld; ids: Seeded; runtime: ExtensionRuntime }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w, { role });
  const ids = await seedOwnedTree(w.tree);
  w.backgroundTabs.serve(URL, PAGE);
  return { w, ids, runtime: await startRuntime(w) };
}

async function save(w: FakeExtensionWorld, runtime: ExtensionRuntime, followUp: string) {
  const node = await w.tree.createBookmark(followUp, 'Story', URL);
  runtime.onBookmarkEvent({ kind: 'created', node });
  await runtime.idle();
  return sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id);
}

// --- Tests ---

describe('Background-tab capture on the writer', () => {
  it('Given a writer and no tab showing a save (made on a phone), When it arrives in Follow Up, Then ingest carries a background_tab capture', async () => {
    const { w, ids, runtime } = await setup();
    const ingest = await save(w, runtime, ids.followUp);
    expect(ingest?.capture).toEqual({ source: 'background_tab', ...PAGE });
    expect(w.backgroundTabs.opened).toEqual([URL]);
  });

  it('Given a save already in Follow Up at a full hello (the backlog re-sent on every hello), When it is re-sent, Then no background tab is opened for it', async () => {
    const { w, ids } = await setup();
    expect(sentOf(w, 'ingest').map((r) => r.bookmark.node_id)).toEqual([ids.saved]);
    expect(w.backgroundTabs.opened).toEqual([]);
  });

  it('Given a writer whose link just dropped (role unknown until the next hello), When a save no tab shows arrives, Then after the reconnect ingest carries a background_tab capture', async () => {
    const { w, ids, runtime } = await setup();
    await w.daemon().drop('disconnected');
    const node = await w.tree.createBookmark(ids.followUp, 'Story', URL);
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();
    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)?.capture).toEqual({ source: 'background_tab', ...PAGE });
    expect(w.backgroundTabs.opened).toEqual([URL]);
  });

  it("Given a writer whose link just dropped, When a save no tab shows arrives and the worker is terminated before the reconnect, Then the next worker's hello still sends it with a background_tab capture", async () => {
    const { w, ids, runtime } = await setup();
    await w.daemon().drop('disconnected');
    const node = await w.tree.createBookmark(ids.followUp, 'Story', URL);
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)?.capture).toEqual({ source: 'background_tab', ...PAGE });
    expect(w.backgroundTabs.opened).toEqual([URL]);
  });

  it('Given a background capture owed from before a restart, When a later hello re-sends the backlog, Then no background tab is opened again', async () => {
    const { w, ids, runtime } = await setup();
    await w.daemon().drop('disconnected');
    runtime.onBookmarkEvent({ kind: 'created', node: await w.tree.createBookmark(ids.followUp, 'Story', URL) });
    await runtime.idle();
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    expect(w.backgroundTabs.opened).toEqual([URL]);
  });

  it('Given a writer whose save the daemon answered internal, When the worker is terminated during the backoff, Then the next worker re-sends the identical frame (same id and capture) without opening another tab', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let refused = false;
    const internalOnce = (r: RequestMessage): ResponseMessage | undefined => {
      if (r.type !== 'ingest' || r.bookmark.url !== URL || refused) return undefined;
      refused = true;
      return { v: 1, type: 'error', re: r.id, code: 'internal', message: 'database is locked' };
    };
    scriptDaemon(w, { role: 'writer' }, internalOnce);
    const ids = await seedOwnedTree(w.tree);
    w.backgroundTabs.serve(URL, PAGE);
    const first = await save(w, await startRuntime(w), ids.followUp);
    expect(first?.capture).toEqual({ source: 'background_tab', ...PAGE });
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    const again = sentOf(w, 'ingest').find((r) => r.bookmark.url === URL);
    expect(again).toEqual(first);
    expect(w.backgroundTabs.opened).toEqual([URL]);
  });

  it('Given a reader host, When a save no tab shows arrives, Then no background tab is opened and ingest carries source none', async () => {
    const { w, ids, runtime } = await setup('reader');
    expect((await save(w, runtime, ids.followUp))?.capture).toEqual({ source: 'none', text: '' });
    expect(w.backgroundTabs.opened).toEqual([]);
  });

  it('Given the setting is turned off, When a save no tab shows arrives, Then no background tab is opened and the setting is kept', async () => {
    const { w, ids, runtime } = await setup();
    expect(await runtime.page({ kind: 'settings.set', capture_in_background: false })).toMatchObject({
      ok: true,
      capture_in_background: false,
      capture_from_tab: true,
    });
    expect((await save(w, runtime, ids.followUp))?.capture).toEqual({ source: 'none', text: '' });
    expect(w.backgroundTabs.opened).toEqual([]);
    expect((await w.storage.loadSettings())?.capture_in_background).toBe(false);
  });

  it('Given open-tab capture is off but background capture is on, When a save arrives, Then the background tab is still used', async () => {
    const { w, ids, runtime } = await setup();
    await runtime.page({ kind: 'settings.set', capture_from_tab: false });
    w.tabs.open(URL, { title: 'open', text: 'from the open tab' });
    expect((await save(w, runtime, ids.followUp))?.capture).toMatchObject({ source: 'background_tab' });
  });

  it('Given fresh settings, When the overview is read, Then background capture shows as on', async () => {
    const { runtime } = await setup();
    expect(await runtime.page({ kind: 'overview' })).toMatchObject({ ok: true, overview: { settings: { capture_in_background: true } } });
  });
});
