// clock.ts -- the Clock port: the one source of "now" for use cases (snapshot
// taken_at, observed_at). Injected, never read from a global.

import type { EpochMs } from '../domain/values.js';

export interface Clock {
  /** Milliseconds since the Unix epoch; never less than a previous read. */
  now(): EpochMs;
}
