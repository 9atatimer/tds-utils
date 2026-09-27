// system.test.ts -- the two adapters that need no browser API: the wall clock
// and the UUIDv4 source run the same port contracts their fakes run.

import { describe, expect, it } from 'vitest';
import { SystemClock } from '../../../src/adapters/clock.js';
import { CryptoIdSource } from '../../../src/adapters/idSource.js';
import { describeClockContract } from '../../port-contracts/clock.contract.js';
import { describeIdSourceContract } from '../../port-contracts/idSource.contract.js';

describeClockContract('SystemClock', () => new SystemClock());
describeIdSourceContract('CryptoIdSource', () => new CryptoIdSource());

describe('SystemClock', () => {
  it('Given a wall clock that steps backwards, When read, Then now() holds at the latest value instead', () => {
    const readings = [5_000, 4_000, 6_000];
    const clock = new SystemClock(() => readings.shift() ?? 0);
    expect([clock.now(), clock.now(), clock.now()]).toEqual([5_000, 5_000, 6_000]);
  });

  it('Given a fractional wall clock, When read, Then now() is whole milliseconds', () => {
    expect(new SystemClock(() => 1_234.7).now()).toBe(1_234);
  });
});
