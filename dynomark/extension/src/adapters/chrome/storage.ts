/// <reference types="chrome" />
// storage.ts -- the StoragePort on chrome.storage.local: the extension's
// durable state (settings, the LocalIndex, the in-flight batch cursor)
// survives a service-worker restart there. The browser serializes values, so
// each load is a fresh copy. `prefix` namespaces the keys (the integration
// suite runs beside a live extension's own state).

import type { BatchCursor } from '../../domain/batch.js';
import type { LocalIndex } from '../../domain/search.js';
import type { Settings } from '../../domain/settings.js';
import type { StoragePort } from '../../ports/storage.js';

// --- Types ---

/** The part of chrome.storage.StorageArea this adapter uses. */
export interface StorageAreaApi {
  get(keys: string | string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string | string[]): Promise<void>;
}

// --- Constants ---

const KEYS = { settings: 'settings', index: 'local_index', cursor: 'batch_cursor' } as const;

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

  private async read<T>(key: string): Promise<T | undefined> {
    const items = await this.area.get(this.prefix + key);
    return items[this.prefix + key] as T | undefined;
  }

  private write(key: string, value: unknown): Promise<void> {
    return this.area.set({ [this.prefix + key]: value });
  }
}
