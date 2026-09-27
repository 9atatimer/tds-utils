// issuedMoves.test.ts -- the moves the extension made and the browser has not
// reported: one entry per move (a node moved twice is remembered twice),
// forgotten one at a time, a bounded number, the oldest going first.

import { describe, expect, it } from 'vitest';
import { MAX_ISSUED_MOVES, withIssued, withoutIssued } from '../../../src/domain/issuedMoves.js';

describe('Issued moves', () => {
  it('Given a node moved twice into the same folder, When one report is consumed, Then one entry remains', () => {
    const move = { node_id: '42', parent_id: '17' };
    expect(withoutIssued(withIssued(withIssued([], move), move), move)).toEqual([move]);
  });

  it('Given no entry for a node and destination, When a report of that move is consumed, Then there is nothing to forget', () => {
    expect(withoutIssued(withIssued([], { node_id: '42', parent_id: '17' }), { node_id: '42', parent_id: '18' })).toBeUndefined();
  });

  it('Given the bound reached, When one more move is remembered, Then the oldest is dropped', () => {
    let moves = withIssued([], { node_id: 'first', parent_id: '1' });
    for (let n = 1; n <= MAX_ISSUED_MOVES; n += 1) moves = withIssued(moves, { node_id: String(n), parent_id: '1' });
    expect(moves).toHaveLength(MAX_ISSUED_MOVES);
    expect(moves.some((m) => m.node_id === 'first')).toBe(false);
  });
});
