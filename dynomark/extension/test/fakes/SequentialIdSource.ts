// SequentialIdSource.ts -- a deterministic IdSource: UUIDv4-shaped ids whose
// last group counts up from 1.

import type { Id } from '../../src/domain/values.js';
import type { IdSource } from '../../src/ports/idSource.js';

export class SequentialIdSource implements IdSource {
  private n = 0;

  next(): Id {
    this.n += 1;
    return `00000000-0000-4000-8000-${String(this.n).padStart(12, '0')}`;
  }
}
