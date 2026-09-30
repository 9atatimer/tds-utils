// idSource.contract.ts -- what every IdSource must do (contract v1 README,
// "Envelope": request ids are random with at least 122 bits -- a UUIDv4 --
// and never reused for a different body).

import { describe, expect, it } from 'vitest';
import type { IdSource } from '../../src/ports/idSource.js';
import { IdSchema } from '../../src/wire/values.js';

// --- Constants ---

/** RFC 9562 UUID version 4, variant 10xx, lower-case hex. */
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Registers the IdSource contract suite for one implementation. */
export function describeIdSourceContract(name: string, make: () => IdSource): void {
  describe(`IdSource contract -- ${name}`, () => {
    it('Given an id source, When an id is drawn, Then it is a UUIDv4 that is also a valid contract Id', () => {
      const id = make().next();
      expect(id).toMatch(UUID_V4);
      expect(IdSchema.safeParse(id).success).toBe(true);
    });

    it('Given 1000 draws, When compared, Then no id repeats', () => {
      const ids = make();
      const drawn = Array.from({ length: 1000 }, () => ids.next());
      expect(new Set(drawn).size).toBe(1000);
    });
  });
}
