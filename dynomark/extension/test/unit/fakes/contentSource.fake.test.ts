// contentSource.fake.test.ts -- the ContentSourcePort fake honours the port contract.

import { FakeTabs } from '../../fakes/FakeTabs.js';
import { describeContentSourceContract } from '../../port-contracts/contentSource.contract.js';

describeContentSourceContract('FakeTabs', () => {
  const tabs = new FakeTabs();
  return {
    content: tabs,
    openTab: (url, page) => Promise.resolve(tabs.open(url, page)),
    openUnreadableTab: (url) => Promise.resolve(tabs.open(url, 'unreadable')),
  };
});
