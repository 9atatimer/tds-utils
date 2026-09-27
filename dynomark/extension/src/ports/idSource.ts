// idSource.ts -- the IdSource port: request ids and the profile id (contract
// v1 README, "Envelope": random, at least 122 bits, a UUIDv4, never reused).

import type { Id } from '../domain/values.js';

export interface IdSource {
  /** A fresh UUIDv4, never returned before. */
  next(): Id;
}
