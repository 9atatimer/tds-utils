// chromeHistory.test.ts -- the chrome.history adapter runs the HistoryPort
// contract over a tiny stand-in for chrome.history.

import { describe, expect, it } from 'vitest';
import { ChromeHistory } from '../../../src/adapters/chrome/history.js';
import { describeHistoryContract } from '../../port-contracts/history.contract.js';
import { HistoryApiStub } from '../../stubs/chromeHistory.js';

describeHistoryContract('ChromeHistory (stubbed chrome.history)', () => {
  const api = new HistoryApiStub();
  return { history: new ChromeHistory(api), seedVisit: (url, at) => Promise.resolve(api.addVisit(url, at)) };
});

describe('ChromeHistory', () => {
  it('Given fractional visit times, When read, Then each is whole EpochMs', async () => {
    const api = new HistoryApiStub();
    api.addVisit('https://tokio.rs/', 1_700_000_000_123.456);
    expect(await new ChromeHistory(api).visitsTo('https://tokio.rs/')).toEqual([{ visited_at: 1_700_000_000_123 }]);
  });
});
