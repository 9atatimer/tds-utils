// history.contract.ts -- what every HistoryPort must do. Frecency is built by
// asking for the visits of each identity the extension holds, never by
// normalizing history URLs (contract v1 README, "Identity"), so the port
// matches a URL exactly.

import { describe, expect, it } from 'vitest';
import type { EpochMs, Url } from '../../src/domain/values.js';
import type { HistoryPort } from '../../src/ports/history.js';

/** A HistoryPort plus the out-of-band way to put a visit into the browser's history. */
export interface HistoryHarness {
  readonly history: HistoryPort;
  seedVisit(url: Url, at: EpochMs): Promise<void>;
}

/** Registers the HistoryPort contract suite for one implementation. */
export function describeHistoryContract(name: string, make: () => HistoryHarness): void {
  describe(`HistoryPort contract -- ${name}`, () => {
    it('Given three visits to a URL seeded out of order, When its visits are read, Then all three come back oldest first', async () => {
      const { history, seedVisit } = make();
      await seedVisit('https://tokio.rs/', 3_000);
      await seedVisit('https://tokio.rs/', 1_000);
      await seedVisit('https://tokio.rs/', 2_000);
      expect(await history.visitsTo('https://tokio.rs/')).toEqual([{ visited_at: 1_000 }, { visited_at: 2_000 }, { visited_at: 3_000 }]);
    });

    it('Given a URL never visited, When its visits are read, Then there are none', async () => {
      expect(await make().history.visitsTo('https://never.example/')).toEqual([]);
    });

    it('Given visits to variants of a URL, When the exact URL is read, Then only its own visits count (no normalization)', async () => {
      const { history, seedVisit } = make();
      await seedVisit('https://tokio.rs/tokio/tutorial', 1_000);
      await seedVisit('https://tokio.rs/tokio/tutorial?utm_source=x', 2_000);
      await seedVisit('https://tokio.rs/tokio/tutorial/', 3_000);
      await seedVisit('https://tokio.rs/tokio/tutorial#intro', 4_000);
      expect(await history.visitsTo('https://tokio.rs/tokio/tutorial')).toEqual([{ visited_at: 1_000 }]);
    });
  });
}
