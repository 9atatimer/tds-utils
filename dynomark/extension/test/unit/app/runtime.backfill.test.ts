// runtime.backfill.test.ts -- the settings page's backfill (design, Open
// Question 3: run the existing tree through capture and indexing at first
// install, searchable, not re-filed, and at what rate; contract v1, "Jobs":
// an ingest with backfill true is never offered a batch). Every existing
// bookmark outside Follow Up and Graveyard is ingested once with backfill
// true and no capture (the daemon fetches), a chunk at a time with a pause
// between chunks, and a worker restart resumes from the stored progress.

import { describe, expect, it } from 'vitest';
import { BACKFILL_CHUNK, BACKFILL_PAUSE_MS } from '../../../src/app/backfill.js';
import type { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { NodeId } from '../../../src/domain/values.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { seedOwnedTree, type Seeded } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, startRuntime, type ExtraAnswers } from '../../fixtures/runtime.js';

// --- Builders ---

const EXTRA_BOOKMARKS = BACKFILL_CHUNK * 2 + 4;

async function setup(extra: ExtraAnswers = () => undefined): Promise<{
  w: FakeExtensionWorld;
  ids: Seeded;
  candidates: NodeId[];
  runtime: ExtensionRuntime;
}> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  scriptDaemon(w, {}, extra);
  const ids = await seedOwnedTree(w.tree);
  const candidates = [ids.usersOwn];
  for (let i = 0; i < EXTRA_BOOKMARKS; i += 1)
    candidates.push((await w.tree.createBookmark(ids.bar, `B${i}`, `https://b${i}.example/`)).id);
  return { w, ids, candidates, runtime: await startRuntime(w) };
}

function backfilled(w: FakeExtensionWorld): Extract<RequestMessage, { type: 'ingest' }>[] {
  return sentOf(w, 'ingest').filter((r) => r.backfill);
}

async function drain(w: FakeExtensionWorld, runtime: ExtensionRuntime): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await w.timer().advance(BACKFILL_PAUSE_MS);
    await runtime.idle();
  }
}

// --- Tests ---

describe('Backfill -- every existing bookmark, once, as backfill', () => {
  it('Given bookmarks outside Follow Up, When backfill runs to the end, Then each is ingested once with backfill true, its path and no capture', async () => {
    const { w, ids, candidates, runtime } = await setup();
    expect(await runtime.page({ kind: 'backfill.start' })).toMatchObject({
      ok: true,
      kind: 'backfill.start',
      backfill: { total: candidates.length },
    });
    await runtime.idle();
    await drain(w, runtime);
    const sent = backfilled(w);
    expect(sent.map((r) => r.bookmark.node_id)).toEqual(candidates);
    expect(sent.every((r) => r.capture === undefined)).toBe(true);
    expect(sent[0]?.bookmark).toMatchObject({ node_id: ids.usersOwn, url: 'https://mail.example/', path: { root: 'bar', names: [] } });
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({ ok: true, overview: { backfill: { total: candidates.length, done: candidates.length, running: false } } });
  });

  it('Given more candidates than a chunk, When started, Then one chunk goes at once and the next only after the pause', async () => {
    const { w, runtime } = await setup();
    await runtime.page({ kind: 'backfill.start' });
    await runtime.idle();
    expect(backfilled(w)).toHaveLength(BACKFILL_CHUNK);
    await w.timer().advance(BACKFILL_PAUSE_MS - 1);
    await runtime.idle();
    expect(backfilled(w)).toHaveLength(BACKFILL_CHUNK);
    await w.timer().advance(1);
    await runtime.idle();
    expect(backfilled(w)).toHaveLength(BACKFILL_CHUNK * 2);
  });

  it('Given a backfill running, When started again, Then it does not start over', async () => {
    const { w, candidates, runtime } = await setup();
    await runtime.page({ kind: 'backfill.start' });
    await runtime.idle();
    expect(await runtime.page({ kind: 'backfill.start' })).toMatchObject({ ok: true, backfill: { running: true } });
    await drain(w, runtime);
    expect(backfilled(w).map((r) => r.bookmark.node_id)).toEqual(candidates);
  });

  it('Given the daemon refuses one ingest as invalid, When backfilling, Then that one is skipped and reported and the rest go on', async () => {
    const refuse = (r: RequestMessage): ResponseMessage | undefined =>
      r.type === 'ingest' && r.bookmark.url === 'https://b3.example/'
        ? { v: 1, type: 'error', re: r.id, code: 'invalid', message: 'no' }
        : undefined;
    const { w, candidates, runtime } = await setup(refuse);
    await runtime.page({ kind: 'backfill.start' });
    await runtime.idle();
    await drain(w, runtime);
    expect(backfilled(w)).toHaveLength(candidates.length);
    const page = await runtime.page({ kind: 'overview' });
    expect(page.ok && page.kind === 'overview' ? page.overview.problems.join('\n') : '').toContain('https://b3.example/');
    expect(page).toMatchObject({ ok: true, overview: { backfill: { done: candidates.length } } });
  });
});

describe('Backfill -- resumable across worker restarts', () => {
  it('Given a worker terminated after the first chunk, When a new worker says hello, Then the backfill resumes from the stored progress', async () => {
    const { w, candidates, runtime } = await setup();
    await runtime.page({ kind: 'backfill.start' });
    await runtime.idle();
    w.restart();
    scriptDaemon(w);
    const next = await startRuntime(w);
    await drain(w, next);
    expect(backfilled(w).map((r) => r.bookmark.node_id)).toEqual(candidates.slice(BACKFILL_CHUNK));
  });

  it('Given a finished backfill, When a new worker says hello, Then nothing is backfilled again', async () => {
    const { w, runtime } = await setup();
    await runtime.page({ kind: 'backfill.start' });
    await runtime.idle();
    await drain(w, runtime);
    w.restart();
    scriptDaemon(w);
    await drain(w, await startRuntime(w));
    expect(backfilled(w)).toEqual([]);
  });

  it('Given the daemon is unreachable, When backfill is started, Then the page is told and nothing is stored', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w);
    w.connection().unreachable(true);
    const runtime = await startRuntime(w);
    expect(await runtime.page({ kind: 'backfill.start' })).toMatchObject({ ok: false });
    expect(await w.storage.loadBackfill()).toBeUndefined();
  });
});
