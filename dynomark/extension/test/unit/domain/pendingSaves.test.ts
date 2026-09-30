// pendingSaves.test.ts -- the saves kept until the daemon answers them: one
// per node and url, a few at most, and at most one maximum capture's worth of
// text, the oldest going first.

import { describe, expect, it } from 'vitest';
import {
  MAX_PENDING_SAVES,
  MAX_PENDING_TEXT,
  pendingFor,
  withPending,
  withoutPending,
  type PendingSave,
} from '../../../src/domain/pendingSaves.js';

// --- Builders ---

function pending(n: number, text = 'signed-in text'): PendingSave {
  return {
    id: `req-${n}`,
    bookmark: {
      node_id: String(n),
      url: `https://p${n}.example/`,
      title: `P${n}`,
      path: { root: 'bar', names: ['Follow Up'] },
      date_added: 1,
    },
    capture: { source: 'background_tab', text, title: `P${n}` },
  };
}

// --- Tests ---

describe('Pending saves', () => {
  it('Given a save kept for a node and url, When a newer request for the same pair is kept, Then only the newer one is found', () => {
    const newer = { ...pending(1), id: 'req-9' };
    const saves = withPending(withPending([], pending(1)), newer);
    expect(saves).toEqual([newer]);
    expect(pendingFor(saves, '1', 'https://p1.example/')).toEqual(newer);
  });

  it('Given as many saves as the bound, When one more is kept, Then the oldest is dropped', () => {
    let saves: PendingSave[] = [];
    for (let n = 0; n <= MAX_PENDING_SAVES; n += 1) saves = withPending(saves, pending(n));
    expect(saves).toHaveLength(MAX_PENDING_SAVES);
    expect(pendingFor(saves, '0', 'https://p0.example/')).toBeUndefined();
    expect(pendingFor(saves, String(MAX_PENDING_SAVES), `https://p${MAX_PENDING_SAVES}.example/`)).toBeDefined();
  });

  it('Given kept text near the bound, When a save that would pass it is kept, Then older saves are dropped until the text fits', () => {
    const half = 'x'.repeat(MAX_PENDING_TEXT / 2);
    const saves = withPending(withPending(withPending([], pending(1, half)), pending(2, half)), pending(3, 'y'));
    expect(saves.map((s) => s.id)).toEqual(['req-2', 'req-3']);
  });

  it('Given a save whose text alone passes the bound, When kept, Then it is not, and an older one for the same pair is gone too', () => {
    const saves = withPending(withPending([pending(2)], pending(1)), { ...pending(1, 'x'.repeat(MAX_PENDING_TEXT + 1)), id: 'req-9' });
    expect(saves).toEqual([pending(2)]);
  });

  it('Given kept saves, When one request is answered, Then only that one is forgotten', () => {
    expect(withoutPending([pending(1), pending(2)], 'req-1')).toEqual([pending(2)]);
  });
});
