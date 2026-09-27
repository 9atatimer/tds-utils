// runtime.writer.test.ts -- the writer marker, extension side (design, Key
// Decisions "Two writers", MVP: refuse on a writer marker in the owned tree;
// task-030: a writer that sees another host's marker refuses every
// write-producing use case and surfaces it in the settings page; contract v1,
// "Writer marker (MVP)"). After a full hello the extension asks writer.status;
// the settings page shows it; while a conflict is reported the extension
// applies no batch (it asks again before rejecting, so a cleared conflict
// does not linger); a writer_conflict refusal counts as a report; once the
// user removes the stale marker, the next snapshot re-asks and the conflict
// clears.

import { describe, expect, it } from 'vitest';
import { SNAPSHOT_DEBOUNCE_MS, type ExtensionRuntime } from '../../../src/app/runtime.js';
import type { WriteBatch } from '../../../src/domain/batch.js';
import type { RequestMessage, ResponseMessage } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { DYNOMARK, seedOwnedTree, type Seeded } from '../../fixtures/ownedTree.js';
import { scriptDaemon, sentOf, sentTypes, startRuntime } from '../../fixtures/runtime.js';

// --- Builders ---

interface Daemon {
  conflict: boolean;
}

function writerAnswers(daemon: Daemon) {
  return (r: RequestMessage): ResponseMessage | undefined => {
    if (r.type === 'writer.status') {
      return {
        v: 1,
        type: 'writer.status.result',
        re: r.id,
        role: 'writer',
        host_id: 'mbp',
        own_marker: true,
        other_writers: daemon.conflict ? ['work-laptop'] : [],
        conflict: daemon.conflict,
      };
    }
    if (r.type === 'undo') return { v: 1, type: 'error', re: r.id, code: 'writer_conflict', message: 'marker of host work-laptop present' };
    return undefined;
  };
}

async function setup(conflict: boolean): Promise<{ w: FakeExtensionWorld; ids: Seeded; runtime: ExtensionRuntime; daemon: Daemon }> {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  const daemon = { conflict };
  scriptDaemon(w, {}, writerAnswers(daemon));
  const ids = await seedOwnedTree(w.tree);
  return { w, ids, runtime: await startRuntime(w), daemon };
}

const BATCH: WriteBatch = {
  batch_id: 'batch-go',
  operations: [{ op: 'create_folder', index: 0, parent: DYNOMARK, title: 'Go' }],
};

async function offer(w: FakeExtensionWorld, runtime: ExtensionRuntime): Promise<RequestMessage | undefined> {
  await w.daemon().emit({ v: 1, type: 'batch.offer', event_id: 'evt-go', batch: BATCH });
  await runtime.idle();
  return sentOf(w, 'batch.receipt').at(-1);
}

// --- Tests ---

describe('Writer status -- asked after a full hello, shown in settings', () => {
  it('Given a full hello, When the connect routine runs, Then writer.status is asked after the index pull', async () => {
    const { w } = await setup(false);
    expect(sentTypes(w).slice(0, 4)).toEqual(['hello', 'tree.snapshot', 'events.replay', 'index.pull']);
    expect(sentTypes(w)).toContain('writer.status');
  });

  it('Given another host is writer too, When the settings overview is read, Then it carries the conflict and the other writer', async () => {
    const { runtime } = await setup(true);
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({
      ok: true,
      overview: { writer: { conflict: true, other_writers: ['work-laptop'], own_marker: true, host_id: 'mbp' } },
    });
  });

  it('Given a daemon that cannot answer writer.status, When connected, Then the connect routine still completes', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    scriptDaemon(w, {}, (r) =>
      r.type === 'writer.status' ? { v: 1, type: 'error', re: r.id, code: 'internal', message: 'boom' } : undefined,
    );
    const ids = await seedOwnedTree(w.tree);
    await startRuntime(w);
    expect(sentOf(w, 'ingest').map((r) => r.bookmark.node_id)).toEqual([ids.saved]);
  });
});

describe('Writer conflict -- no batch is applied while one is reported', () => {
  it('Given a reported conflict, When a batch is offered, Then status is asked again and, still in conflict, the receipt is REJECTED writer_conflict with the tree untouched', async () => {
    const { w, runtime } = await setup(true);
    const before = await w.tree.readTree();
    const asked = sentOf(w, 'writer.status').length;
    const receipt = await offer(w, runtime);
    expect(sentOf(w, 'writer.status').length).toBeGreaterThan(asked);
    expect(receipt).toMatchObject({ receipt: { state: 'REJECTED', reason: 'writer_conflict', batch_id: 'batch-go' } });
    expect((await w.tree.readTree()).nodes).toEqual(before.nodes);
  });

  it('Given a reported conflict that has since cleared, When a batch is offered, Then the fresh status lets it apply', async () => {
    const { w, runtime, daemon } = await setup(true);
    daemon.conflict = false;
    expect(await offer(w, runtime)).toMatchObject({ receipt: { state: 'APPLIED' } });
  });

  it('Given a request refused writer_conflict, When a batch is offered, Then the conflict counts as reported and status is asked first', async () => {
    const { w, runtime, daemon } = await setup(false);
    daemon.conflict = true;
    expect(await runtime.page({ kind: 'undo', batch_id: 'batch-1' })).toMatchObject({ ok: false, code: 'writer_conflict' });
    const asked = sentOf(w, 'writer.status').length;
    expect(await offer(w, runtime)).toMatchObject({ receipt: { state: 'REJECTED', reason: 'writer_conflict' } });
    expect(sentOf(w, 'writer.status').length).toBe(asked + 1);
  });

  it('Given no conflict, When a batch is offered, Then status is not asked again and the batch applies', async () => {
    const { w, runtime } = await setup(false);
    const asked = sentOf(w, 'writer.status').length;
    expect(await offer(w, runtime)).toMatchObject({ receipt: { state: 'APPLIED' } });
    expect(sentOf(w, 'writer.status')).toHaveLength(asked);
  });
});

describe('Writer conflict -- clearing the stale marker is a user edit in the tree', () => {
  it('Given a conflict, When the user removes the stale marker and the debounced snapshot goes out, Then status is asked again and the conflict clears', async () => {
    const { w, ids, runtime, daemon } = await setup(true);
    const marker = await w.tree.createFolder(ids.dynomark, 'dynomark-writer:work-laptop');
    await w.tree.move(marker.id, ids.graveyard);
    daemon.conflict = false;
    runtime.onBookmarkEvent({ kind: 'moved', node_id: marker.id, parent_id: ids.graveyard, old_parent_id: ids.dynomark });
    await runtime.idle();
    await w.timer().advance(SNAPSHOT_DEBOUNCE_MS);
    await runtime.idle();
    const last = sentTypes(w).lastIndexOf('writer.status');
    expect(last).toBeGreaterThan(sentTypes(w).lastIndexOf('tree.snapshot'));
    const page = await runtime.page({ kind: 'overview' });
    expect(page).toMatchObject({ ok: true, overview: { writer: { conflict: false } } });
  });
});
