// idSource.fake.test.ts -- the IdSource fake honours the port contract and is
// deterministic, so tests can name the ids a use case will send.

import { describe, expect, it } from 'vitest';
import { SequentialIdSource } from '../../fakes/SequentialIdSource.js';
import { describeIdSourceContract } from '../../port-contracts/idSource.contract.js';

describeIdSourceContract('SequentialIdSource', () => new SequentialIdSource());

describe('SequentialIdSource', () => {
  it('Given two fresh sources, When each draws twice, Then both yield the same predictable sequence', () => {
    const a = new SequentialIdSource();
    const b = new SequentialIdSource();
    expect([a.next(), a.next()]).toEqual([b.next(), b.next()]);
    expect(new SequentialIdSource().next()).toBe('00000000-0000-4000-8000-000000000001');
  });
});
