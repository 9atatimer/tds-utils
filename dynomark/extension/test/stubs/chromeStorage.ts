// chromeStorage.ts -- a tiny chrome.storage.local stand-in: values kept as
// JSON text, as the browser serializes them, so every get is a fresh copy.

import type { StorageAreaApi } from '../../src/adapters/chrome/storage.js';

export class StorageAreaStub implements StorageAreaApi {
  private readonly items = new Map<string, string>();

  get(keys: string | string[]): Promise<Record<string, unknown>> {
    const wanted = typeof keys === 'string' ? [keys] : keys;
    const out: Record<string, unknown> = {};
    for (const key of wanted) {
      const raw = this.items.get(key);
      if (raw !== undefined) out[key] = JSON.parse(raw) as unknown;
    }
    return Promise.resolve(out);
  }

  set(items: Record<string, unknown>): Promise<void> {
    for (const [key, value] of Object.entries(items)) this.items.set(key, JSON.stringify(value));
    return Promise.resolve();
  }

  remove(keys: string | string[]): Promise<void> {
    for (const key of typeof keys === 'string' ? [keys] : keys) this.items.delete(key);
    return Promise.resolve();
  }

  /** Every key currently stored. */
  keys(): string[] {
    return [...this.items.keys()];
  }
}
