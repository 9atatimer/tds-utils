// indexCache.ts -- the LocalIndex and its Frecency held in memory for tier-1
// search on every keystroke (design, Goal 4: 20 ms at 10,000 entries). Loaded
// from storage when the worker starts; refreshed whenever a sync stores a new
// index (the storage it hands the sync reports each save).

import type { Frecency, LocalIndex } from '../domain/search.js';
import type { Clock } from '../ports/clock.js';
import type { HistoryPort } from '../ports/history.js';
import type { StoragePort } from '../ports/storage.js';
import { buildFrecency } from './buildFrecency.js';

// --- The cache ---

export class IndexCache {
  private rows: LocalIndex = [];
  private boost: Frecency = new Map();
  /** Counts replacements, so only the newest one installs its frecency. */
  private generation = 0;

  constructor(
    private readonly deps: { readonly storage: StoragePort; readonly history: HistoryPort; readonly clock: Clock },
    private readonly track: (work: Promise<unknown>) => void,
  ) {}

  /** Load the stored index (if any); its frecency is derived in the background, so a worker's start never waits on history. */
  async load(): Promise<void> {
    const stored = (await this.deps.storage.loadLocalIndex()) ?? [];
    this.track(this.replace(stored));
  }

  index(): LocalIndex {
    return this.rows;
  }

  frecency(): Frecency {
    return this.boost;
  }

  /** `storage`, reporting every stored index to this cache. */
  observing(storage: StoragePort): StoragePort {
    return {
      loadSettings: () => storage.loadSettings(),
      saveSettings: (s) => storage.saveSettings(s),
      loadLocalIndex: () => storage.loadLocalIndex(),
      saveLocalIndex: async (index) => {
        // Searched from memory even when the browser refuses to store it; the refusal still reaches the caller.
        this.track(this.replace(index));
        await storage.saveLocalIndex(index);
      },
      loadCursor: () => storage.loadCursor(),
      saveCursor: (c) => storage.saveCursor(c),
      clearCursor: () => storage.clearCursor(),
      loadBackfill: () => storage.loadBackfill(),
      saveBackfill: (p) => storage.saveBackfill(p),
      loadOwedCaptures: () => storage.loadOwedCaptures(),
      saveOwedCaptures: (ids) => storage.saveOwedCaptures(ids),
      loadPendingSaves: () => storage.loadPendingSaves(),
      savePendingSaves: (saves) => storage.savePendingSaves(saves),
      loadPendingMoves: () => storage.loadPendingMoves(),
      savePendingMoves: (moves) => storage.savePendingMoves(moves),
    };
  }

  /** The rows at once; the frecency once built, unless a newer index replaced them meanwhile. */
  private async replace(index: LocalIndex): Promise<void> {
    const generation = (this.generation += 1);
    this.rows = index;
    const boost = await buildFrecency(index, this.deps);
    if (generation === this.generation) this.boost = boost;
  }
}
