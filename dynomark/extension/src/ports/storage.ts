// storage.ts -- the StoragePort: the extension's durable state -- settings,
// the rebuildable LocalIndex and the in-flight batch cursor (design, "The
// extension"), plus backfill progress (Open Question 3; resumable across
// worker restarts) and the Follow Up saves still owed a background capture
// (bounded by Follow Up's size), and the saves sent and not yet answered
// (bounded in count and text; domain/pendingSaves.ts). Values, not references.

import type { BackfillProgress } from '../domain/backfill.js';
import type { BatchCursor } from '../domain/batch.js';
import type { PendingSave } from '../domain/pendingSaves.js';
import type { LocalIndex } from '../domain/search.js';
import type { Settings } from '../domain/settings.js';
import type { NodeId } from '../domain/values.js';

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
  /** Follow Up saves that arrived while the role was unknown: the next full hello's backlog captures each with the background chain allowed. */
  loadOwedCaptures(): Promise<readonly NodeId[] | undefined>;
  saveOwedCaptures(node_ids: readonly NodeId[]): Promise<void>;
  /** Follow Up saves sent and not yet answered ingest.result: a later worker re-sends each unchanged. */
  loadPendingSaves(): Promise<readonly PendingSave[] | undefined>;
  savePendingSaves(saves: readonly PendingSave[]): Promise<void>;
}
