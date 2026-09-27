// FakeStorage.ts -- an in-memory StoragePort. Values are stored as JSON text,
// as chrome.storage serializes them, so no caller can share a reference with
// what is stored. Keep one instance across a simulated service-worker
// restart: it is the only extension state that survives one.

import type { BatchCursor } from '../../src/domain/batch.js';
import type { LocalIndex } from '../../src/domain/search.js';
import type { Settings } from '../../src/domain/settings.js';
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
