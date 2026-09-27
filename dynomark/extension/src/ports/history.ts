// history.ts -- the HistoryPort: browser history, the Frecency source
// (design, "Frecency"; seam table, "Browser history").

import type { Visit } from '../domain/search.js';
import type { Url } from '../domain/values.js';

export interface HistoryPort {
  /** Every recorded visit to exactly this URL (no normalization), oldest first. */
  visitsTo(url: Url): Promise<readonly Visit[]>;
}
