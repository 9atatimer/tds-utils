/// <reference types="chrome" />
// storage.ts -- the StoragePort on chrome.storage.local: the extension's
// durable state (settings, the LocalIndex, the in-flight batch cursor,
// backfill progress, the saves owed a background capture, the saves sent and
// not yet answered) survives a service-worker restart there. The browser serializes values, so
// each load is a fresh copy. `prefix` namespaces the keys (the integration
// suite runs beside a live extension's own state).

import type { BackfillProgress } from '../../domain/backfill.js';
import type { BatchCursor } from '../../domain/batch.js';
import type { PendingSave } from '../../domain/pendingSaves.js';
import type { LocalIndex } from '../../domain/search.js';
import type { Settings } from '../../domain/settings.js';
import type { NodeId } from '../../domain/values.js';
import type { StoragePort } from '../../ports/storage.js';

// --- Types ---

/** The part of chrome.storage.StorageArea this adapter uses. */
export interface StorageAreaApi {
  get(keys: string | string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string | string[]): Promise<void>;
}

// --- Constants ---

const KEYS = {
  settings: 'settings',
  index: 'local_index',
  cursor: 'batch_cursor',
  backfill: 'backfill',
  owed: 'owed_captures',
  pending: 'pending_saves',
} as const;

// --- The adapter ---

export class ChromeStorage implements StoragePort {
  private readonly prefix: string;

  constructor(
    private readonly area: StorageAreaApi = chrome.storage.local,
    options: { readonly prefix?: string } = {},
  ) {
    this.prefix = options.prefix ?? '';
  }

  loadSettings(): Promise<Settings | undefined> {
    return this.read<Settings>(KEYS.settings);
  }

  saveSettings(settings: Settings): Promise<void> {
    return this.write(KEYS.settings, settings);
  }

  loadLocalIndex(): Promise<LocalIndex | undefined> {
    return this.read<LocalIndex>(KEYS.index);
  }

  saveLocalIndex(index: LocalIndex): Promise<void> {
    return this.write(KEYS.index, index);
  }

  loadCursor(): Promise<BatchCursor | undefined> {
    return this.read<BatchCursor>(KEYS.cursor);
  }

  saveCursor(cursor: BatchCursor): Promise<void> {
    return this.write(KEYS.cursor, cursor);
  }

  clearCursor(): Promise<void> {
    return this.area.remove(this.prefix + KEYS.cursor);
  }

  loadBackfill(): Promise<BackfillProgress | undefined> {
    return this.read<BackfillProgress>(KEYS.backfill);
  }

  saveBackfill(progress: BackfillProgress): Promise<void> {
    return this.write(KEYS.backfill, progress);
  }

  loadOwedCaptures(): Promise<readonly NodeId[] | undefined> {
    return this.read<NodeId[]>(KEYS.owed);
  }

  saveOwedCaptures(node_ids: readonly NodeId[]): Promise<void> {
    return this.write(KEYS.owed, node_ids);
  }

  loadPendingSaves(): Promise<readonly PendingSave[] | undefined> {
    return this.read<PendingSave[]>(KEYS.pending);
  }

  savePendingSaves(saves: readonly PendingSave[]): Promise<void> {
    return this.write(KEYS.pending, saves);
  }

  private async read<T>(key: string): Promise<T | undefined> {
    const items = await this.area.get(this.prefix + key);
    return items[this.prefix + key] as T | undefined;
  }

  private write(key: string, value: unknown): Promise<void> {
    return this.area.set({ [this.prefix + key]: value });
  }
}
