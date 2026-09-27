// storage.contract.ts -- what every StoragePort must do. The extension's
// durable state is settings, the rebuildable LocalIndex and the in-flight
// batch cursor (design, "The extension"), plus backfill progress (Open
// Question 3, resumable across worker restarts); storage is the only
// thing besides the browser's own data that survives a service-worker
// restart, and it stores values, not references.

import { describe, expect, it } from 'vitest';
import type { BackfillProgress } from '../../src/domain/backfill.js';
import type { BatchCursor } from '../../src/domain/batch.js';
import type { LocalIndex } from '../../src/domain/search.js';
import type { Settings } from '../../src/domain/settings.js';
import type { StoragePort } from '../../src/ports/storage.js';

// --- Builders ---

const BACKFILL: BackfillProgress = { started_at: 1_790_000_000_000, node_ids: ['15', '16', '17'], next_index: 1 };

const SETTINGS: Settings = { profile_id: '00000000-0000-4000-8000-00000000abcd', transport: 'native_messaging' };

const INDEX: LocalIndex = [
  {
    identity: 'https://tokio.rs/tokio/tutorial',
    title: 'Tokio tutorial',
    path: { root: 'bar', names: ['Dynomark', 'Rust', 'Async'] },
    tags: ['rust', 'async'],
    summary: 'Step-by-step guide to async Rust with Tokio.',
  },
];

const CURSOR: BatchCursor = {
  batch_id: 'batch-0101',
  op_count: 3,
  next_index: 2,
  outcomes: [
    { outcome: 'applied', index: 0, node_id: '16', changed: true },
    { outcome: 'skipped', index: 1, reason: 'node_missing' },
  ],
  started: 2,
};

/** Registers the StoragePort contract suite for one implementation. */
export function describeStorageContract(name: string, make: () => StoragePort): void {
  describe(`StoragePort contract -- ${name}`, () => {
    it('Given fresh storage, When each value is loaded, Then all are absent', async () => {
      const storage = make();
      expect(await storage.loadSettings()).toBeUndefined();
      expect(await storage.loadLocalIndex()).toBeUndefined();
      expect(await storage.loadCursor()).toBeUndefined();
    });

    it('Given settings, a LocalIndex and a cursor saved, When loaded, Then each round-trips equal', async () => {
      const storage = make();
      await storage.saveSettings(SETTINGS);
      await storage.saveLocalIndex(INDEX);
      await storage.saveCursor(CURSOR);
      expect(await storage.loadSettings()).toEqual(SETTINGS);
      expect(await storage.loadLocalIndex()).toEqual(INDEX);
      expect(await storage.loadCursor()).toEqual(CURSOR);
    });

    it('Given a saved value, When loaded twice, Then each load is a copy, not the saved object or each other', async () => {
      const storage = make();
      await storage.saveCursor(CURSOR);
      const first = await storage.loadCursor();
      const second = await storage.loadCursor();
      expect(first).not.toBe(CURSOR);
      expect(first).not.toBe(second);
      expect(first?.outcomes).not.toBe(CURSOR.outcomes);
    });

    it('Given a saved cursor, When saved again, Then the later value replaces the earlier', async () => {
      const storage = make();
      await storage.saveCursor(CURSOR);
      await storage.saveCursor({ batch_id: 'batch-0102', op_count: 2, next_index: 0, outcomes: [] });
      expect(await storage.loadCursor()).toEqual({ batch_id: 'batch-0102', op_count: 2, next_index: 0, outcomes: [] });
    });

    it('Given backfill progress, When saved, loaded, and saved again, Then it round-trips and the later value replaces the earlier', async () => {
      const storage = make();
      expect(await storage.loadBackfill()).toBeUndefined();
      await storage.saveBackfill(BACKFILL);
      expect(await storage.loadBackfill()).toEqual(BACKFILL);
      await storage.saveBackfill({ ...BACKFILL, next_index: 3 });
      expect(await storage.loadBackfill()).toEqual({ ...BACKFILL, next_index: 3 });
    });

    it('Given all three values saved, When the cursor is cleared, Then only the cursor is gone', async () => {
      const storage = make();
      await storage.saveSettings(SETTINGS);
      await storage.saveLocalIndex(INDEX);
      await storage.saveCursor(CURSOR);
      await storage.clearCursor();
      expect(await storage.loadCursor()).toBeUndefined();
      expect(await storage.loadSettings()).toEqual(SETTINGS);
      expect(await storage.loadLocalIndex()).toEqual(INDEX);
    });
  });
}
