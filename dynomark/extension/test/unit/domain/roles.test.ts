// roles.test.ts -- contract v1 README, "Connection lifecycle": the version
// table gives the mode (equal full; extension newer read_only; extension
// older refused), and the mode decides which requests continue (read_only:
// hello, status, events.replay, events.ack, index.pull, search, ask,
// placement.explain; refused: nothing but hello).

import { describe, expect, it } from 'vitest';
import { isPermitted, modeFor } from '../../../src/domain/roles.js';

describe('Connection mode from versions, and what each mode permits', () => {
  it('Given the extension and daemon versions, When the mode is derived, Then equal is full, extension newer is read_only, extension older is refused', () => {
    expect(modeFor(1, 1)).toBe('full');
    expect(modeFor(2, 1)).toBe('read_only');
    expect(modeFor(1, 2)).toBe('refused');
  });

  it('Given a read_only connection, When requests are checked, Then only the read-only set is permitted', () => {
    const permitted = ['hello', 'status', 'events.replay', 'events.ack', 'index.pull', 'search', 'ask', 'placement.explain'];
    const refused = ['ingest', 'tree.snapshot', 'move.observed', 'batch.receipt', 'undo', 'diff.accept', 'folder.flags.set', 'job.retry'];
    expect(permitted.every((t) => isPermitted('read_only', t))).toBe(true);
    expect(refused.filter((t) => isPermitted('read_only', t))).toEqual([]);
  });

  it('Given a refused connection, When requests are checked, Then only hello is permitted; Given full, Then everything is', () => {
    expect(isPermitted('refused', 'hello')).toBe(true);
    expect(isPermitted('refused', 'search')).toBe(false);
    expect(isPermitted('full', 'batch.receipt')).toBe(true);
  });
});
