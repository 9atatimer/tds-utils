// clock.fake.test.ts -- the Clock fake honours the port contract, and moves
// only when a test moves it (no real time in unit tests).

import { describe, expect, it } from 'vitest';
import { FakeClock } from '../../fakes/FakeClock.js';
import { describeClockContract } from '../../port-contracts/clock.contract.js';

describeClockContract('FakeClock', () => new FakeClock(1_790_000_000_000));

describe('FakeClock', () => {
  it('Given a start time, When advanced by 1500 ms, Then now() is exactly 1500 ms later and stays there', () => {
    const clock = new FakeClock(1_000);
    clock.advance(1_500);
    expect(clock.now()).toBe(2_500);
    expect(clock.now()).toBe(2_500);
  });

  it('Given a negative advance, When applied, Then it throws rather than run time backwards', () => {
    expect(() => new FakeClock(1_000).advance(-1)).toThrow(RangeError);
  });
});
