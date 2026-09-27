// observeMove.test.ts -- design, "The extension", Record feedback:
// record_move on every onMoved whose source and destination are owned; the
// adapter sets origin from the batch operations the extension itself issued;
// contract v1: each such move is reported as `move.observed` with its origin
// (the daemon discards all but user moves on the writer), and moves of nodes
// the in-flight batch names are origin extension.

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
  return { v: 1, type: 'move.observed.result', re: r.id };
}

function deps() {
  const transport = new FakeTransport();
  transport.autoAnswer(acknowledging);
  const clock = new FakeClock(NOW);
  const moves = new ReportedMoves(new FakeStorage());
  return { transport, ids: new SequentialIdSource(), clock, moves, timer: new FakeTimer(clock), track: () => undefined };
}

// --- Tests ---

describe('Behavior: A user move becomes feedback -- observeMove(observed, role, context, { transport, ids, clock, moves, timer, track })', () => {
  it('Given the user moves a node between owned folders on the writer, When observed, Then feedback exists and move.observed carries origin user', async () => {
    const d = deps();
    const feedback = await observeMove(
      { node_id: '42', url: 'https://tokio.rs/', from: ASYNC, to: RUST },
      'writer',
      { owned_roots: ROOTS, in_flight: new Set() },
      d,
    );
    expect(feedback).toEqual({ node_id: '42', url: 'https://tokio.rs/', from: ASYNC, to: RUST, origin: 'user', observed_at: NOW });
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move).toEqual(feedback);
  });

  it('Given the node is named by the batch in flight, When its move is observed, Then move.observed carries origin extension and there is no feedback', async () => {
    const d = deps();
    const feedback = await observeMove(
      { node_id: '42', from: ROOTS.follow_up, to: ASYNC },
      'writer',
      { owned_roots: ROOTS, in_flight: new Set(['42']) },
      d,
    );
    expect(feedback).toBeUndefined();
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move.origin).toBe('extension');
  });

  it('Given a reader host, When a user move between owned folders is observed, Then it is still reported but there is no feedback', async () => {
    const d = deps();
    const feedback = await observeMove({ node_id: '42', from: ASYNC, to: RUST }, 'reader', { owned_roots: ROOTS, in_flight: new Set() }, d);
    expect(feedback).toBeUndefined();
    expect(MoveObservedSchema.parse(d.transport.sent[0]).move.origin).toBe('user');
  });

  it('Given a move out of the owned roots, When observed, Then nothing is sent and there is no feedback', async () => {
    const d = deps();
    const feedback = await observeMove(
      { node_id: '42', from: ASYNC, to: { root: 'bar', names: [] } },
      'writer',
      { owned_roots: ROOTS, in_flight: new Set() },
      d,
    );
    expect(feedback).toBeUndefined();
    expect(d.transport.sent).toEqual([]);
  });
});
