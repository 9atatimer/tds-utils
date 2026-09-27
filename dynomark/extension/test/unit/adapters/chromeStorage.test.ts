// chromeStorage.test.ts -- the chrome.storage.local adapter runs the
// StoragePort contract over a tiny stand-in for the storage area (the same
// suite runs against the real area in test/integration).

import { describe, expect, it } from 'vitest';
import { ChromeStorage } from '../../../src/adapters/chrome/storage.js';
import { describeStorageContract } from '../../port-contracts/storage.contract.js';
import { StorageAreaStub } from '../../stubs/chromeStorage.js';

describeStorageContract('ChromeStorage (stubbed chrome.storage.local)', () => new ChromeStorage(new StorageAreaStub()));

describe('ChromeStorage', () => {
  it('Given a key prefix, When values are saved, Then every key it writes carries the prefix and clearing the cursor removes only its key', async () => {
    const area = new StorageAreaStub();
    const storage = new ChromeStorage(area, { prefix: 'test:' });
    await storage.saveSettings({ profile_id: 'p', transport: 'native_messaging' });
    await storage.saveCursor({ batch_id: 'b', op_count: 1, next_index: 0, outcomes: [] });
    await storage.clearCursor();
    expect(area.keys()).toEqual(['test:settings']);
  });
});
