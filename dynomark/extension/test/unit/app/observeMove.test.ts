// observeMove.test.ts -- design, "The extension", Record feedback:
// every onMoved whose source and destination are owned is reported as
// `move.observed` with its origin (contract v2); moves of nodes the in-flight
// batch names are origin extension. The daemon's feedback_of alone decides
// which become MoveFeedback (issue #422).

import { describe, expect, it } from 'vitest';
import { ReportedMoves, observeMove } from '../../../src/app/observeMove.js';
import { MoveObservedSchema, type RequestMessage, type ResponseMessage } from '../../../src/wire/messages.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeStorage } from '../../fakes/FakeStorage.js';
import { FakeTimer } from '../../fakes/FakeTimer.js';
import { FakeTransport } from '../../fakes/FakeTransport.js';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';
import { ROOTS } from '../../fixtures/ownedTree.js';

// --- Builders ---

const NOW = 1_790_000_100_000;
const ASYNC = { root: 'bar' as const, names: ['Dynomark', 'Rust', 'Async'] };
const RUST = { root: 'bar' as const, names: ['Dynomark', 'Rust'] };

function acknowledging(r: RequestMessage): ResponseMessage {
  if (r.type !== 'move.observed') throw new Error(`unexpected ${r.type}`);
  return { v: 2, type: 'move.observed.result', re: r.id };
}

function deps() {
  const transport = new FakeTransport();
  transport.autoAnswer(acknowledging);
  const clock = new FakeClock(NOW);
  const moves = new ReportedMoves(new FakeStorage());
  return { transport, ids: new SequentialIdSource(), clock, moves, timer: new FakeTimer(clock), track: () => undefined };
}

// --- Tests ---

describe('Record feedback -- observeMove(observed, context, { transport, ids, clock, moves, timer, track }) reports owned moves; the daemon decides feedback (issue #422)', () => {
  it('Given the user moves a node between owned folders, When observed, Then move.observed carries it with origin user and the time', async () => {
    const d = deps();
    await observeMove({ node_id: '42', url: 'https://tokio.rs/', from: ASYNC, to: RUST }, { owned_roots: ROOTS, in_flight: new Set() }, d);
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move).toEqual({
      node_id: '42',
      url: 'https://tokio.rs/',
      from: ASYNC,
      to: RUST,
      origin: 'user',
      observed_at: NOW,
    });
  });

  it('Given the node is named by the batch in flight, When its move is observed, Then move.observed still reports it, with origin extension', async () => {
    const d = deps();
    await observeMove({ node_id: '42', from: ROOTS.follow_up, to: ASYNC }, { owned_roots: ROOTS, in_flight: new Set(['42']) }, d);
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move.origin).toBe('extension');
  });

  it('Given a folder (no url) moved between owned folders, When observed, Then move.observed still reports it', async () => {
    const d = deps();
    await observeMove({ node_id: '7', from: ASYNC, to: RUST }, { owned_roots: ROOTS, in_flight: new Set() }, d);
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move).toMatchObject({ node_id: '7', origin: 'user' });
  });

  it('Given a move out of the owned roots, When observed, Then nothing is sent', async () => {
    const d = deps();
    await observeMove({ node_id: '42', from: ASYNC, to: { root: 'bar', names: [] } }, { owned_roots: ROOTS, in_flight: new Set() }, d);
    expect(d.transport.sent).toEqual([]);
  });
});
