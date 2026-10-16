// runtime.lifecycle.test.ts -- the background composition's workflow on the
// fakes (design, "The extension": Watch Follow Up, Settings; contract v2
// README, "Connection lifecycle" and "Endpoint"). On start the worker loads
// or creates its settings (a profile id generated once), resolves Follow Up
// (creating it under the bar when there is none; reporting extra ones),
// says hello, and after a full hello re-sends ingest for every node in
// Follow Up. A lost link is reconnected with backoff and says hello again; a
// superseded one never is.

import { describe, expect, it } from 'vitest';
import { FOLLOW_UP_TITLE } from '../../../src/domain/followUp.js';
import { RECONNECT_BACKOFF } from '../../../src/domain/backoff.js';
import { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { LocalIndexRow } from '../../../src/domain/search.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { scriptedDaemon } from '../../fixtures/daemon.js';
import { FOLLOW_UP, seedOwnedTree } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, sentTypes, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

function world(): FakeExtensionWorld {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w);
  return w;
}

function row(identity: string): LocalIndexRow {
  return { identity, title: identity, path: { root: 'bar', names: ['Dynomark'] }, tags: [], summary: '' };
}

/** Let every queued continuation run: one turn of the event loop (no wall-clock wait). */
function settle(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

// --- Tests ---

describe('Start -- ExtensionRuntime.start()', () => {
  it('Given a fresh profile, When started, Then Follow Up is created under the bar, settings keep a new profile id, and hello names both', async () => {
    const w = world();
    await startRuntime(w);
    const tree = await w.tree.readTree();
    const followUp = tree.nodes.filter((n) => n.kind === 'folder' && n.title === FOLLOW_UP_TITLE);
    expect(followUp).toHaveLength(1);
    expect(followUp[0]?.parent_id).toBe(tree.root_ids.bar);
    const settings = await w.storage.loadSettings();
    expect(settings).toMatchObject({ transport: 'native_messaging' });
    const [hello] = sentOf(w, 'hello');
    expect(hello).toMatchObject({ profile_id: settings?.profile_id, follow_up: { root: 'bar', names: ['Follow Up'] } });
    expect(sentTypes(w).slice(0, 4)).toEqual(['hello', 'tree.snapshot', 'events.replay', 'index.pull']);
  });

  it('Given stored settings, When a new worker starts, Then its hello reuses the stored profile id', async () => {
    const w = world();
    await w.storage.saveSettings({ profile_id: 'profile-kept', transport: 'native_messaging' });
    await startRuntime(w);
    expect(sentOf(w, 'hello')[0]?.profile_id).toBe('profile-kept');
  });

  it('Given Follow Up under Other and another on the bar, When started, Then hello names the bar one and the overview reports the other', async () => {
    const w = world();
    const { root_ids } = await w.tree.readTree();
    const extra = await w.tree.createFolder(root_ids.other, 'Follow Up');
    await w.tree.createFolder(root_ids.bar, 'Follow Up');
    const runtime = await startRuntime(w);
    expect(sentOf(w, 'hello')[0]?.follow_up).toEqual({ root: 'bar', names: ['Follow Up'] });
    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain(extra.id);
  });

  it('Given bookmarks already in Follow Up, When the full hello completes, Then each is ingested once, with backfill false', async () => {
    const w = world();
    const ids = await seedOwnedTree(w.tree);
    await startRuntime(w);
    const ingests = sentOf(w, 'ingest');
    expect(ingests.map((r) => r.bookmark.node_id)).toEqual([ids.saved]);
    expect(ingests[0]).toMatchObject({ backfill: false, bookmark: { path: FOLLOW_UP } });
  });

  it('Given a refused hello (a newer daemon), When started, Then nothing follows hello: no Follow Up backlog is ingested', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, { v: 3, mode: 'refused' });
    await seedOwnedTree(w.tree);
    await startRuntime(w);
    expect(sentTypes(w)).toEqual(['hello']);
  });
});

describe('Reconnect -- a lost link is re-opened with backoff; hello goes first every time', () => {
  it('Given a connected worker, When the link drops with nothing in flight, Then after the first backoff it says hello and replays events again', async () => {
    const w = world();
    const runtime = await startRuntime(w);
    await w.daemon().drop('disconnected');
    await w.timer().advance(RECONNECT_BACKOFF.base_ms - 1);
    expect(sentOf(w, 'hello')).toHaveLength(1);
    await w.timer().advance(1);
    await runtime.idle();
    expect(sentOf(w, 'hello')).toHaveLength(2);
    expect(sentOf(w, 'events.replay')).toHaveLength(2);
  });

  it('Given an unreachable daemon, When the worker starts, Then attempts back off (doubling) and the first one that reaches it says hello', async () => {
    const w = world();
    w.connection().unreachable(true);
    const runtime = await startRuntime(w);
    const attempts = () => sentOf(w, 'hello').length;
    const first = attempts();
    await w.timer().advance(RECONNECT_BACKOFF.base_ms);
    const second = attempts();
    await w.timer().advance(RECONNECT_BACKOFF.base_ms * 2 - 1);
    expect(attempts()).toBe(second);
    await w.timer().advance(1);
    expect(attempts()).toBeGreaterThan(second);
    expect(second).toBeGreaterThan(first);
    w.connection().unreachable(false);
    await w.timer().advance(RECONNECT_BACKOFF.base_ms * 4);
    await runtime.idle();
    expect(sentTypes(w)).toContain('events.replay');
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({ ok: true, overview: { link: { state: 'connected' } } });
  });

  it('Given the connection is superseded, When time passes, Then nothing more reaches the wire, not even hello', async () => {
    const w = world();
    const runtime = await startRuntime(w);
    await w.daemon().drop('superseded');
    const before = w.connection().sent.length;
    await w.timer().advance(RECONNECT_BACKOFF.max_ms * 4);
    await runtime.idle();
    expect(w.connection().sent).toHaveLength(before);
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({ ok: true, overview: { link: { state: 'superseded' } } });
  });

  it('Given a worker restart, When the new worker starts, Then it says hello on its own connection with the same profile id', async () => {
    const w = world();
    await startRuntime(w);
    const profile = sentOf(w, 'hello')[0]?.profile_id;
    w.restart();
    scriptDaemon(w);
    await startRuntime(w);
    expect(sentOf(w, 'hello')[0]?.profile_id).toBe(profile);
  });
});

describe('Connect routine -- a step that fails is reported, the rest still runs, and the routine is tried again', () => {
  it('Given the daemon answers the first index.pull internal, When the connect routine fails, Then it is reported, the backlog and writer status still run, and after the backoff the routine runs again', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let pulls = 0;
    scriptDaemon(w, {}, (r) =>
      r.type === 'index.pull' && (pulls += 1) === 1
        ? { v: 2, type: 'error', re: r.id, code: 'internal', message: 'store closed' }
        : undefined,
    );
    const ids = await seedOwnedTree(w.tree);
    const runtime = await startRuntime(w);

    expect(sentOf(w, 'ingest').map((r) => r.bookmark.node_id)).toEqual([ids.saved]);
    expect(sentOf(w, 'writer.status')).toHaveLength(1);
    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain('store closed');

    await w.timer().advance(RECONNECT_BACKOFF.base_ms);
    await runtime.idle();
    expect(sentOf(w, 'index.pull')).toHaveLength(2);
    expect(sentOf(w, 'hello')).toHaveLength(1);
  });
});

describe('Daemon restart -- the gap while no daemon listens is a lost link, retried by reconnecting, never a problem (issue #524)', () => {
  it('Given the connect routine has an index.pull in flight, When the daemon restarts (its host answers busy until the new one listens), Then no problem is reported and after the backoff the routine and writer status run on the new daemon', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    let pullInFlight: () => void = () => undefined;
    const pulled = new Promise<void>((resolve) => (pullInFlight = resolve));
    let pulls = 0;
    const lifecycle = scriptedDaemon({});
    w.connection().autoAnswer((r) => {
      if (r.type === 'index.pull' && (pulls += 1) === 1) {
        pullInFlight();
        return undefined; // the old daemon is stopped before it answers
      }
      return lifecycle(r);
    });
    const runtime = new ExtensionRuntime(w.worker());
    await runtime.start();
    await pulled;

    w.connection().daemonNotRunning(true);
    await w.daemon().drop('disconnected');
    await runtime.idle();
    w.connection().daemonNotRunning(false);
    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();

    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems : undefined).toEqual([]);
    const types = sentTypes(w);
    const lastHello = types.lastIndexOf('hello');
    expect(types.slice(lastHello)).toEqual(
      expect.arrayContaining(['hello', 'tree.snapshot', 'events.replay', 'index.pull', 'writer.status']),
    );
    expect(page).toMatchObject({ ok: true, overview: { link: { state: 'connected' } } });
  });
});

describe('Start does not wait on frecency -- history is a ranking input, not a precondition', () => {
  it('Given a stored index whose history lookups have not answered, When a worker starts, Then start resolves and hello is sent', async () => {
    const w = world();
    await w.storage.saveLocalIndex([row('https://a.example/'), row('https://b.example/')]);
    w.history.hold();
    const runtime = new ExtensionRuntime(w.worker());
    let started = false;
    const starting = runtime.start().then(() => (started = true));
    await settle();
    const early = { started, hellos: sentOf(w, 'hello').length };
    w.history.release();
    await starting;
    await runtime.idle();
    expect(early).toEqual({ started: true, hellos: 1 });
  });

  it('Given a stored index with one identity whose history lookup fails, When a worker starts, Then it starts, says hello and answers pages', async () => {
    const w = world();
    await w.storage.saveLocalIndex([row('https://a.example/'), row('https://broken.example/')]);
    w.history.refuse('https://broken.example/');
    const runtime = new ExtensionRuntime(w.worker());
    await runtime.start();
    await runtime.idle();
    expect(sentOf(w, 'hello')).toHaveLength(1);
    expect(await runtime.page({ kind: 'overview' })).toMatchObject({ ok: true });
  });
});

describe('Background work that a reconnect re-runs -- a lost link in the gap is not a problem', () => {
  it('Given a connected host whose daemon stops while a save is being ingested (the ingest is lost with the link, and its re-sends meet no daemon), When the gap lasts, Then no problem is reported, and once the daemon is back the next hello ingests it', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const lifecycle = scriptedDaemon({ role: 'reader' });
    const URL = 'https://gap.example/';
    let stopped = false;
    w.connection().autoAnswer((r) => {
      if (r.type !== 'ingest' || r.bookmark.url !== URL || stopped) return lifecycle(r);
      stopped = true;
      w.connection().daemonNotRunning(true);
      void Promise.resolve().then(() => w.daemon().drop('disconnected'));
      return undefined;
    });
    const ids = await seedOwnedTree(w.tree);
    const runtime = await startRuntime(w);

    const node = await w.tree.createBookmark(ids.followUp, 'Gap', URL);
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();
    const during = await runtime.page({ kind: 'overview' });
    w.connection().daemonNotRunning(false);
    await w.timer().advance(RECONNECT_BACKOFF.max_ms);
    await runtime.idle();

    expect(stopped).toBe(true);
    expect(during.ok && during.kind === 'overview' ? during.overview.problems : undefined).toEqual([]);
    expect(sentOf(w, 'ingest').filter((r) => r.bookmark.node_id === node.id).length).toBeGreaterThan(1);
    const after = await runtime.page({ kind: 'overview' });
    expect(after.ok && after.kind === 'overview' ? after.overview.problems : undefined).toEqual([]);
  });

  it('Given a connected writer, When a tracked step fails for a real reason (the daemon answers invalid), Then it is still reported', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, { role: 'writer' }, (r) =>
      r.type === 'ingest' && r.bookmark.url === 'https://bad.example/'
        ? { v: 2, type: 'error', re: r.id, code: 'invalid', message: 'ingest refused' }
        : undefined,
    );
    const ids = await seedOwnedTree(w.tree);
    const runtime = await startRuntime(w);

    const node = await w.tree.createBookmark(ids.followUp, 'Bad', 'https://bad.example/');
    runtime.onBookmarkEvent({ kind: 'created', node });
    await runtime.idle();

    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain('ingest refused');
  });
});
