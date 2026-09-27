// move.test.ts -- design Behaviors row "A user move becomes feedback", the
// domain rule: record_move(move, role) -> MoveFeedback or none. Given a Move
// of origin user between owned folders on the writer, Then feedback exists;
// Given origin extension or role reader, Then none. The origin comes from the
// batch operations the extension itself issued (design glossary, "Move").

import { describe, expect, it } from 'vitest';
import type { WriteBatch } from '../../../src/domain/batch.js';
import { inFlightNodes, isOwnedMove, moveOrigin, recordMove, type Move } from '../../../src/domain/move.js';
import type { OwnedRoots } from '../../../src/domain/tree.js';

// --- Builders ---

const ROOTS: OwnedRoots = {
  follow_up: { root: 'bar', names: ['Follow Up'] },
  dynomark: { root: 'bar', names: ['Dynomark'] },
  graveyard: { root: 'bar', names: ['Graveyard'] },
};

function move(origin: Move['origin']): Move {
  return {
    node_id: '42',
    from: { root: 'bar', names: ['Dynomark', 'Rust', 'Async'] },
    to: { root: 'bar', names: ['Dynomark', 'Rust'] },
    origin,
    observed_at: 1_790_000_100_000,
  };
}

// --- Tests ---

describe('Behavior: A user move becomes feedback -- recordMove(move, role)', () => {
  it('Given a move of origin user on the writer, When recorded, Then it is feedback', () => {
    expect(recordMove(move('user'), 'writer')).toEqual(move('user'));
  });

  it('Given a move of origin extension on the writer, When recorded, Then there is no feedback', () => {
    expect(recordMove(move('extension'), 'writer')).toBeUndefined();
  });

  it('Given a move of origin user on a reader, When recorded, Then there is no feedback', () => {
    expect(recordMove(move('user'), 'reader')).toBeUndefined();
  });
});

describe('Which moves are recorded, and with which origin', () => {
  it('Given moves within and across the owned roots, When checked, Then only moves whose source and destination are both owned count', () => {
    const inDynomark = { root: 'bar' as const, names: ['Dynomark', 'Rust'] };
    expect(isOwnedMove(inDynomark, ROOTS.graveyard, ROOTS)).toBe(true);
    expect(isOwnedMove(ROOTS.follow_up, inDynomark, ROOTS)).toBe(true);
    expect(isOwnedMove(inDynomark, { root: 'bar', names: [] }, ROOTS)).toBe(false);
    expect(isOwnedMove({ root: 'other', names: ['Dynomark'] }, inDynomark, ROOTS)).toBe(false);
  });

  it('Given a batch in flight, When its node set is taken, Then it holds exactly the nodes its move and remove ops name', () => {
    const batch: WriteBatch = {
      batch_id: 'b',
      operations: [
        { op: 'create_folder', index: 0, parent: ROOTS.dynomark, title: 'Go' },
        { op: 'move', index: 1, node_id: '42', to: ROOTS.dynomark, expect: { parent_id: '10' } },
        { op: 'remove', index: 2, node_id: '43', expect: { parent_id: '10' } },
        { op: 'create', index: 3, parent: ROOTS.dynomark, title: 'x', url: 'https://x.example/' },
      ],
    };
    expect([...inFlightNodes(batch)].sort()).toEqual(['42', '43']);
  });

  it('Given the in-flight node set, When a move is observed, Then a named node is origin extension and any other is origin user', () => {
    const inFlight = new Set(['42']);
    expect(moveOrigin('42', inFlight)).toBe('extension');
    expect(moveOrigin('77', inFlight)).toBe('user');
  });
});
