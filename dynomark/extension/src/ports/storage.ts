// storage.ts -- the StoragePort: the extension's durable state -- settings,
// the rebuildable LocalIndex and the in-flight batch cursor (design, "The
// extension"), plus backfill progress (Open Question 3; resumable across
// worker restarts). Values, not references.

import type { BackfillProgress } from '../domain/backfill.js';
import type { BatchCursor } from '../domain/batch.js';
import type { LocalIndex } from '../domain/search.js';
import type { Settings } from '../domain/settings.js';

export interface StoragePort {
  loadSettings(): Promise<Settings | undefined>;
  saveSettings(settings: Settings): Promise<void>;
  loadLocalIndex(): Promise<LocalIndex | undefined>;
  saveLocalIndex(index: LocalIndex): Promise<void>;
  loadCursor(): Promise<BatchCursor | undefined>;
  /** Durable before it resolves: a restart after this call sees the cursor. */
  saveCursor(cursor: BatchCursor): Promise<void>;
  clearCursor(): Promise<void>;
  loadBackfill(): Promise<BackfillProgress | undefined>;
  saveBackfill(progress: BackfillProgress): Promise<void>;
}
