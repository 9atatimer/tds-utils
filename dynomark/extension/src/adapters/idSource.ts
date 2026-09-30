// idSource.ts -- the IdSource adapter: crypto.randomUUID, a UUIDv4 with 122
// random bits (contract v1 README, "Envelope"). Available in extension
// service workers, extension pages and Node.

import type { Id } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';

export class CryptoIdSource implements IdSource {
  next(): Id {
    return crypto.randomUUID();
  }
}
