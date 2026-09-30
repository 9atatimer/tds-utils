// pendingMoves.test.ts -- the move reports kept until the daemon answers them:
// one per request id, a bounded number, the oldest going first.

import { describe, expect, it } from 'vitest';
import { MAX_PENDING_MOVES, withPendingMove, withoutPendingMove, type PendingMove } from '../../../src/domain/pendingMoves.js';

// --- Builders ---

function pending(n: number): PendingMove {
  return {
    id: `req-${n}`,
    move: {
      node_id: String(n),
      from: { root: 'bar', names: ['Follow Up'] },
      to: { root: 'bar', names: ['Dynomark', 'Rust'] },
      origin: 'user',
      observed_at: 1_790_000_000_000 + n,
    },
  };
}

// --- Tests ---

describe('Pending move reports', () => {
  it('Given a report kept, When the same request is kept again, Then it is kept once', () => {
    expect(withPendingMove(withPendingMove([], pending(1)), pending(1))).toEqual([pending(1)]);
  });

  it('Given the bound reached, When one more report is kept, Then the oldest is dropped and the newest kept', () => {
    let moves: PendingMove[] = [];
    for (let n = 0; n <= MAX_PENDING_MOVES; n += 1) moves = withPendingMove(moves, pending(n));
    expect(moves).toHaveLength(MAX_PENDING_MOVES);
    expect(moves[0]).toEqual(pending(1));
    expect(moves.at(-1)).toEqual(pending(MAX_PENDING_MOVES));
  });

  it('Given two reports kept, When one is answered, Then only the other is kept', () => {
    expect(withoutPendingMove([pending(1), pending(2)], 'req-1')).toEqual([pending(2)]);
  });
});
