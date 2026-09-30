// history.fake.test.ts -- the HistoryPort fake honours the port contract.

import { FakeHistory } from '../../fakes/FakeHistory.js';
import { describeHistoryContract } from '../../port-contracts/history.contract.js';

describeHistoryContract('FakeHistory', () => {
  const history = new FakeHistory();
  return { history, seedVisit: (url, at) => Promise.resolve(history.recordVisit(url, at)) };
});
