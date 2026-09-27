// connection.test.ts -- contract v1 README, "Connection lifecycle" and
// "Delivery and replay", on the extension side (design, "Transport
// contract": identity and version; delivery; retryable errors). The first
// exchange on every connection is hello; the mode it returns decides what
// continues (full: everything; read_only: the read-only set; refused:
// nothing but hello); after a full hello the extension sends tree.snapshot
// and events.replay and pulls the index; a request with no answer after a
// reconnect is re-sent with the same id and body; superseded never
// reconnects.

import { describe, expect, it } from 'vitest';
import { Connection, ContractViolation, ModeRefused } from '../../../src/app/connection.js';
import { onConnected } from '../../../src/app/onConnected.js';
import { DaemonError } from '../../../src/app/errors.js';
import type { RequestMessage } from '../../../src/wire/messages.js';
import { HelloSchema } from '../../../src/wire/messages.js';
import { FakeExtensionWorld } from '../../fakes/FakeExtensionWorld.js';
import { scriptedDaemon, type HelloAnswer } from '../../fixtures/daemon.js';
import { FOLLOW_UP, ROOTS, seedOwnedTree } from '../../fixtures/ownedTree.js';

// --- Builders ---

const IDENTITY = { profile_id: 'profile-1', follow_up: FOLLOW_UP };

const EVENTS_REPLAY = { v: 1 as const, type: 'events.replay' as const };

async function setup(hello?: HelloAnswer) {
  const w = new FakeExtensionWorld({ flavor: 'chrome' });
  await seedOwnedTree(w.tree);
  if (hello !== undefined) w.connection().autoAnswer(scriptedDaemon(hello));
  const worker = w.worker();
  const connection: Connection = new Connection(IDENTITY, worker, (outcome) => onConnected(outcome, { ...worker, transport: connection }));
  return { w, connection };
}

function types(sent: readonly RequestMessage[]): string[] {
  return sent.map((r) => r.type);
}

// --- Tests ---

describe('Hello handling -- Connection(identity, { transport, ids }, onConnected)', () => {
  it('Given mode full, When the first request is sent, Then hello goes first, then tree.snapshot, events.replay and index.pull, then the request', async () => {
    const { w, connection } = await setup({});
    const result = await connection.send({ ...EVENTS_REPLAY, id: 'req-own' });
    expect(result.type).toBe('events.replay.result');
    expect(types(w.connection().sent)).toEqual(['hello', 'tree.snapshot', 'events.replay', 'index.pull', 'events.replay']);
    expect(HelloSchema.parse(w.connection().sent[0])).toMatchObject({ v: 1, profile_id: 'profile-1', follow_up: FOLLOW_UP });
    expect(connection.outcome()).toEqual({ v: 1, mode: 'full', role: 'writer', host_id: 'mbp', owned_roots: ROOTS });
  });

  it('Given mode full, When connected, Then the tree.snapshot sent is the tree as read now', async () => {
    const { w, connection } = await setup({});
    await connection.connect();
    const snapshot = w.connection().sent.find((r) => r.type === 'tree.snapshot');
    expect(snapshot?.type === 'tree.snapshot' ? snapshot.snapshot : undefined).toEqual({
      ...(await w.tree.readTree()),
      taken_at: w.clock.now(),
    });
  });

  it('Given mode read_only, When connected, Then no tree.snapshot is sent, events are replayed and the index pulled, and a write request is refused locally', async () => {
    const { w, connection } = await setup({ mode: 'read_only' });
    await connection.connect();
    expect(types(w.connection().sent)).toEqual(['hello', 'events.replay', 'index.pull']);
    const ingest = {
      v: 1 as const,
      type: 'move.observed' as const,
      id: 'req-m',
      move: { node_id: '1', from: FOLLOW_UP, to: FOLLOW_UP, origin: 'user' as const, observed_at: 1 },
    };
    await expect(connection.send(ingest)).rejects.toBeInstanceOf(ModeRefused);
    expect(types(w.connection().sent)).toEqual(['hello', 'events.replay', 'index.pull']);
  });

  it('Given mode refused, When connected, Then nothing follows hello and every request is refused locally', async () => {
    const { w, connection } = await setup({ mode: 'refused', v: 2 });
    expect(await connection.connect()).toMatchObject({ mode: 'refused' });
    await expect(connection.send({ ...EVENTS_REPLAY, id: 'req-1' })).rejects.toBeInstanceOf(ModeRefused);
    expect(types(w.connection().sent)).toEqual(['hello']);
  });

  it('Given owned_roots.follow_up differs from the hello follow_up, When connected, Then it is a ContractViolation and no request is sent', async () => {
    const { w, connection } = await setup({ owned_roots: { ...ROOTS, follow_up: { root: 'other', names: ['Follow Up'] } } });
    await expect(connection.connect()).rejects.toBeInstanceOf(ContractViolation);
    await expect(connection.send({ ...EVENTS_REPLAY, id: 'req-1' })).rejects.toBeInstanceOf(ContractViolation);
    expect(types(w.connection().sent)).toEqual(['hello']);
  });

  it('Given a mode that contradicts the versions (a v2 daemon answering full), When connected, Then it is a ContractViolation', async () => {
    const { connection } = await setup({ v: 2, mode: 'full' });
    await expect(connection.connect()).rejects.toBeInstanceOf(ContractViolation);
  });

  it('Given the daemon answers hello with error, When connected, Then it rejects with that DaemonError', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    w.connection().autoAnswer((r) => ({ v: 1, type: 'error', re: r.id, code: 'internal', message: 'starting' }));
    const connection = new Connection(IDENTITY, w.worker());
    await expect(connection.connect()).rejects.toBeInstanceOf(DaemonError);
  });
});

describe('Delivery -- a request with no answer is re-sent after a reconnect with the same id and body', () => {
  it('Given the connection drops while a request is in flight, When it reconnects, Then hello comes first and the request is re-sent unchanged', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const daemon = w.daemon();
    const answer = scriptedDaemon({});
    const connection = new Connection(IDENTITY, w.worker());
    const request = { v: 1 as const, type: 'events.ack' as const, id: 'req-ack', event_ids: ['evt-1'] };
    const pending = connection.send(request);
    const hello1 = await daemon.nextRequest();
    await daemon.answer(answer(hello1));
    expect(await daemon.nextRequest()).toEqual(request);
    await daemon.drop('disconnected');
    const hello2 = await daemon.nextRequest();
    expect(hello2.type).toBe('hello');
    expect(hello2.id).not.toBe(hello1.id);
    await daemon.answer(answer(hello2));
    expect(await daemon.nextRequest()).toEqual(request);
    await daemon.answer({ v: 1, type: 'events.ack.result', re: 'req-ack' });
    expect((await pending).type).toBe('events.ack.result');
  });

  it('Given the daemon answers hello_required, When a request is sent, Then the extension says hello again and re-sends the request with the same id', async () => {
    const w = new FakeExtensionWorld({ flavor: 'chrome' });
    const answer = scriptedDaemon({});
    let refusedOnce = false;
    w.connection().autoAnswer((r) => {
      if (r.type === 'events.ack' && !refusedOnce) {
        refusedOnce = true;
        return { v: 1, type: 'error', re: r.id, code: 'hello_required', message: 'daemon restarted' };
      }
      return answer(r);
    });
    const connection = new Connection(IDENTITY, w.worker());
    const result = await connection.send({ v: 1, type: 'events.ack', id: 'req-ack', event_ids: ['evt-1'] });
    expect(result.type).toBe('events.ack.result');
    expect(w.connection().sent.map((r) => `${r.type}:${r.type === 'hello' ? '' : r.id}`)).toEqual([
      'hello:',
      'events.ack:req-ack',
      'hello:',
      'events.ack:req-ack',
    ]);
  });

  it('Given the connection is superseded, When requests are sent, Then they reject superseded and nothing more reaches the wire, not even hello', async () => {
    const { w, connection } = await setup({});
    await connection.connect();
    await w.daemon().drop('superseded');
    const before = w.connection().sent.length;
    await expect(connection.send({ ...EVENTS_REPLAY, id: 'req-2' })).rejects.toMatchObject({ reason: 'superseded' });
    await expect(connection.connect()).rejects.toMatchObject({ reason: 'superseded' });
    expect(w.connection().sent).toHaveLength(before);
  });
});
