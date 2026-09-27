// FakeStorage.ts -- an in-memory StoragePort. Values are stored as JSON text,
// as chrome.storage serializes them, so no caller can share a reference with
// what is stored. Keep one instance across a simulated service-worker
// restart: it is the only extension state that survives one.

import type { BackfillProgress } from '../../src/domain/backfill.js';
import type { BatchCursor } from '../../src/domain/batch.js';
import type { PendingMove } from '../../src/domain/pendingMoves.js';
import type { PendingSave } from '../../src/domain/pendingSaves.js';
import type { LocalIndex } from '../../src/domain/search.js';
import type { Settings } from '../../src/domain/settings.js';
import type { NodeId } from '../../src/domain/values.js';
import type { StoragePort } from '../../src/ports/storage.js';

export class FakeStorage implements StoragePort {
  private readonly items = new Map<string, string>();

  loadSettings(): Promise<Settings | undefined> {
    return Promise.resolve(this.read<Settings>('settings'));
  }

  saveSettings(settings: Settings): Promise<void> {
    return Promise.resolve(this.write('settings', settings));
  }

  loadLocalIndex(): Promise<LocalIndex | undefined> {
    return Promise.resolve(this.read<LocalIndex>('local_index'));
  }

  saveLocalIndex(index: LocalIndex): Promise<void> {
    return Promise.resolve(this.write('local_index', index));
  }

  loadCursor(): Promise<BatchCursor | undefined> {
    return Promise.resolve(this.read<BatchCursor>('batch_cursor'));
  }

  saveCursor(cursor: BatchCursor): Promise<void> {
    return Promise.resolve(this.write('batch_cursor', cursor));
  }

  loadBackfill(): Promise<BackfillProgress | undefined> {
    return Promise.resolve(this.read<BackfillProgress>('backfill'));
  }

  saveBackfill(progress: BackfillProgress): Promise<void> {
    return Promise.resolve(this.write('backfill', progress));
  }

  loadOwedCaptures(): Promise<readonly NodeId[] | undefined> {
    return Promise.resolve(this.read<NodeId[]>('owed_captures'));
  }

  saveOwedCaptures(node_ids: readonly NodeId[]): Promise<void> {
    return Promise.resolve(this.write('owed_captures', node_ids));
  }

  loadPendingSaves(): Promise<readonly PendingSave[] | undefined> {
    return Promise.resolve(this.read<PendingSave[]>('pending_saves'));
  }

  savePendingSaves(saves: readonly PendingSave[]): Promise<void> {
    return Promise.resolve(this.write('pending_saves', saves));
  }

  loadPendingMoves(): Promise<readonly PendingMove[] | undefined> {
    return Promise.resolve(this.read<PendingMove[]>('pending_moves'));
  }

  savePendingMoves(moves: readonly PendingMove[]): Promise<void> {
    return Promise.resolve(this.write('pending_moves', moves));
  }

  clearCursor(): Promise<void> {
    this.items.delete('batch_cursor');
    return Promise.resolve();
  }

  private read<T>(key: string): T | undefined {
    const raw = this.items.get(key);
    return raw === undefined ? undefined : (JSON.parse(raw) as T);
  }

  private write(key: string, value: unknown): void {
    this.items.set(key, JSON.stringify(value));
  }
}
