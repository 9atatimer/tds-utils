// timer.fake.test.ts -- the Timer fake honours the port contract and moves
// the clock it shares with the world, so debounces run on fake time.

import { describe, expect, it } from 'vitest';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeTimer } from '../../fakes/FakeTimer.js';
import { describeTimerContract } from '../../port-contracts/timer.contract.js';

describeTimerContract('FakeTimer', () => {
  const timer = new FakeTimer(new FakeClock(1_000));
  return { timer, elapse: (ms) => timer.advance(ms) };
});

describe('FakeTimer', () => {
  it('Given a callback that schedules another inside the window, When time passes, Then both run and the clock reads each due time', async () => {
    const clock = new FakeClock(1_000);
    const timer = new FakeTimer(clock);
    const seen: number[] = [];
    timer.after(10, () => {
      seen.push(clock.now());
      timer.after(10, () => seen.push(clock.now()));
    });
    await timer.advance(50);
    expect(seen).toEqual([1_010, 1_020]);
    expect(clock.now()).toBe(1_050);
    expect(timer.pending()).toBe(0);
  });
});
