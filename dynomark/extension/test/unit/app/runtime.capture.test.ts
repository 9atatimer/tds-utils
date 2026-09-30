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

  it("Given a writer and a save no tab shows, When the worker is terminated while its background tab loads, Then the next worker's hello sends it with a background_tab capture", async () => {
    const { w, ids, runtime } = await setup();
    w.backgroundTabs.terminateOnNextRead();
    const node = await w.tree.createBookmark(ids.followUp, 'Story', URL);
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)).toBeUndefined();
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.node_id === node.id)?.capture).toEqual({ source: 'background_tab', ...PAGE });
    expect(w.backgroundTabs.opened).toEqual([URL, URL]);
  });

  it('Given a writer whose save the daemon answered busy twice, When the link drops and the same worker reconnects before the next retry, Then the backlog re-sends the identical frame without opening another tab', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let refusals = 0;
    const busyTwice = (r: RequestMessage): ResponseMessage | undefined => {
      if (r.type !== 'ingest' || r.bookmark.url !== URL || refusals >= 2) return undefined;
      refusals += 1;
      return { v: 1, type: 'error', re: r.id, code: 'busy', message: 'model loading' };
    };
    scriptDaemon(w, { role: 'writer' }, busyTwice);
    const ids = await seedOwnedTree(w.tree);
    w.backgroundTabs.serve(URL, PAGE);
    const runtime = await startRuntime(w);
    const first = await save(w, runtime, ids.followUp);
    await w.timer().advance(RECONNECT_BACKOFF.base_ms);
    await runtime.idle();
    expect(refusals).toBe(2);
    await w.daemon().drop('disconnected');
    await w.timer().advance(RECONNECT_BACKOFF.base_ms);
    await runtime.idle();
    const sent = sentOf(w, 'ingest').filter((r) => r.bookmark.url === URL);
    expect(sent.length).toBeGreaterThan(1);
    expect(sent.every((r) => JSON.stringify(r) === JSON.stringify(first))).toBe(true);
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

  it('Given a writer whose save the daemon answered internal, When the same worker re-sends it after the backoff and the daemon takes it, Then the next worker opens no background tab for it', async () => {
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
    const runtime = await startRuntime(w);
    await save(w, runtime, ids.followUp);
    await w.timer().advance(RECONNECT_BACKOFF.base_ms);
    await runtime.idle();
    expect(sentOf(w, 'ingest').filter((r) => r.bookmark.url === URL)).toHaveLength(2);
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    expect(w.backgroundTabs.opened).toEqual([URL]);
    expect(sentOf(w, 'ingest').find((r) => r.bookmark.url === URL)?.capture).toEqual({ source: 'none', text: '' });
  });

  it('Given a pending save the next worker re-sent and the daemon took, When a later worker says hello, Then the backlog sends it with a fresh request and no stored capture', async () => {
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
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    w.restart();
    scriptDaemon(w, { role: 'writer' });
    await startRuntime(w);
    const later = sentOf(w, 'ingest').find((r) => r.bookmark.url === URL);
    expect(later?.id).not.toBe(first?.id);
    expect(later?.capture).toEqual({ source: 'none', text: '' });
  });

  /** Three worker restarts, each a full hello whose backlog re-sends Follow Up; `extra` answers first on every worker. */
  async function restartThrice(w: FakeExtensionWorld, extra?: (r: RequestMessage) => ResponseMessage | undefined): Promise<void> {
    for (let i = 0; i < 3; i++) {
      w.restart();
      scriptDaemon(w, { role: 'writer' }, extra);
      await startRuntime(w);
    }
  }

  it('Given a writer whose save the daemon refuses for good, When later workers say hello, Then no further background tab is opened for it', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const refuse = (r: RequestMessage): ResponseMessage | undefined =>
      r.type === 'ingest' && r.bookmark.url === URL
        ? { v: 1, type: 'error', re: r.id, code: 'invalid', message: 'cannot act on it' }
        : undefined;
    scriptDaemon(w, { role: 'writer' }, refuse);
    const ids = await seedOwnedTree(w.tree);
    w.backgroundTabs.serve(URL, PAGE);
    const runtime = await startRuntime(w);
    await save(w, runtime, ids.followUp);
    await restartThrice(w, refuse);
    expect(w.backgroundTabs.opened).toEqual([URL]);
    expect((await w.storage.loadOwedCaptures()) ?? []).toEqual([]);
  });

  it('Given a writer whose save is answered busy and its retry refused for good, When later workers say hello, Then no further background tab is opened for it', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let answered = 0;
    const busyThenRefuse = (r: RequestMessage): ResponseMessage | undefined => {
      if (r.type !== 'ingest' || r.bookmark.url !== URL) return undefined;
      answered += 1;
      if (answered === 1) return { v: 1, type: 'error', re: r.id, code: 'busy', message: 'model loading' };
      return { v: 1, type: 'error', re: r.id, code: 'invalid', message: 'cannot act on it' };
    };
    scriptDaemon(w, { role: 'writer' }, busyThenRefuse);
    const ids = await seedOwnedTree(w.tree);
    w.backgroundTabs.serve(URL, PAGE);
    const runtime = await startRuntime(w);
    await save(w, runtime, ids.followUp);
    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();
    expect(answered).toBe(2);
    await restartThrice(w, busyThenRefuse);
    expect(w.backgroundTabs.opened).toEqual([URL]);
    expect((await w.storage.loadOwedCaptures()) ?? []).toEqual([]);
  });

  it('Given a writer and a save whose url is over the cap, When it arrives and later workers say hello, Then no background tab is ever opened for it and it is reported', async () => {
    const big = 'https://big.example/?' + 'q'.repeat(70_000);
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, { role: 'writer' });
    const ids = await seedOwnedTree(w.tree);
    w.backgroundTabs.serve(big, PAGE);
    const runtime = await startRuntime(w);
    const node = await w.tree.createBookmark(ids.followUp, 'Big', big);
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();
    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain(`bookmark ${node.id}: url over`);
    await restartThrice(w);
    expect(w.backgroundTabs.opened).toEqual([]);
    expect((await w.storage.loadOwedCaptures()) ?? []).toEqual([]);
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

  it('Given two settings changes sent at once (one per checkbox), When both are answered, Then each builds on the other and both are kept', async () => {
    const { w, runtime } = await setup();
    const [first, second] = await Promise.all([
      runtime.page({ kind: 'settings.set', capture_from_tab: false }),
      runtime.page({ kind: 'settings.set', capture_in_background: false }),
    ]);
    expect(first).toMatchObject({ ok: true, capture_from_tab: false });
    expect(second).toMatchObject({ ok: true, capture_from_tab: false, capture_in_background: false });
    expect(await w.storage.loadSettings()).toMatchObject({ capture_from_tab: false, capture_in_background: false });
    expect(await runtime.page({ kind: 'overview' })).toMatchObject({
      ok: true,
      overview: { settings: { capture_from_tab: false, capture_in_background: false } },
    });
  });

  it('Given fresh settings, When the overview is read, Then background capture shows as on', async () => {
    const { runtime } = await setup();
    expect(await runtime.page({ kind: 'overview' })).toMatchObject({ ok: true, overview: { settings: { capture_in_background: true } } });
  });
});
