// history.test.ts -- the history page's words for a batch and for an undo
// report (design, "Duplicate identity": the parking batch names the existing
// placement; Goal 6: the undo report lists each skipped step with its
// reason). Contract v2 carries both (issue #423).

import { describe, expect, it } from 'vitest';
import { batchWhat, undoReport } from '../../../src/ui/history.js';

describe('History -- a parking batch and the undo report', () => {
  it('Given a parking batch, When its row is described, Then it names the identity and the existing placement', () => {
    const text = batchWhat({
      batch_id: 'batch-0105',
      state: 'APPLIED',
      created_at: 1,
      identity: 'https://tokio.rs/',
      park: { existing: { root: 'bar', names: ['Dynomark', 'Rust'] } },
    });
    expect(text).toContain('https://tokio.rs/');
    expect(text).toContain('already filed in Dynomark / Rust');
  });

  it('Given a filing, an accepted item and an undo, When their rows are described, Then each says what it is', () => {
    expect(batchWhat({ batch_id: 'b', state: 'APPLIED', created_at: 1, identity: 'https://tokio.rs/' })).toBe('https://tokio.rs/');
    expect(batchWhat({ batch_id: 'b', state: 'APPLIED', created_at: 1, diff_item_id: 'item-3' })).toBe('item-3');
    expect(batchWhat({ batch_id: 'b', state: 'APPLIED', created_at: 1, undoes: 'batch-1' })).toBe('undo of batch-1');
  });

  it('Given an undo that dropped a locked folder and kept an owned root, When reported, Then each reason is named', () => {
    const text = undoReport('batch-1', 'batch-2', [
      { index: 2, reason: 'locked' },
      { index: 0, reason: 'owned_root' },
    ]);
    expect(text).toContain('queued as batch-2');
    expect(text).toMatch(/op 2: .*locked/);
    expect(text).toMatch(/op 0: .*(Dynomark|owned root)/);
  });

  it('Given an undo with nothing left, When reported, Then it says so', () => {
    expect(undoReport('batch-1', null, [{ index: 0, reason: 'node_moved' }])).toMatch(/nothing left to revert/);
  });
});
