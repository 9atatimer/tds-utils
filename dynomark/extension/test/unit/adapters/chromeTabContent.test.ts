// chromeTabContent.test.ts -- the open-tab ContentSourcePort on chrome.tabs
// and chrome.scripting runs the port contract over tiny stand-ins; which tab
// is read is the adapter's own choice.

import { describe, expect, it } from 'vitest';
import { ChromeTabContent } from '../../../src/adapters/chrome/tabContent.js';
import { describeContentSourceContract } from '../../port-contracts/contentSource.contract.js';
import { TabsStub } from '../../stubs/chromeTabs.js';

describeContentSourceContract('ChromeTabContent (stubbed chrome.tabs/scripting)', () => {
  const stub = new TabsStub();
  return {
    content: new ChromeTabContent(stub, stub),
    openTab: (url, page) => Promise.resolve(void stub.open(url, page)),
    openUnreadableTab: (url) => Promise.resolve(void stub.open(url, 'unreadable')),
  };
});

describe('ChromeTabContent', () => {
  it('Given two tabs showing the URL, When read, Then the most recently used one is read', async () => {
    const stub = new TabsStub();
    stub.open('https://tokio.rs/', { title: 'older', text: 'old' }, 10);
    stub.open('https://tokio.rs/', { title: 'newer', text: 'new' }, 20);
    expect(await new ChromeTabContent(stub, stub).readTab('https://tokio.rs/')).toEqual({ title: 'newer', text: 'new' });
  });

  it('Given the most recent tab is unreadable and an older one is not, When read, Then the older one is read', async () => {
    const stub = new TabsStub();
    stub.open('https://tokio.rs/', { title: 'older', text: 'old' }, 10);
    stub.open('https://tokio.rs/', 'unreadable', 20);
    expect(await new ChromeTabContent(stub, stub).readTab('https://tokio.rs/')).toEqual({ title: 'older', text: 'old' });
  });

  it('Given no tab shows the URL, When read, Then no script is injected anywhere', async () => {
    const stub = new TabsStub();
    stub.open('https://serde.rs/', { title: 'Serde', text: 'serde' });
    await new ChromeTabContent(stub, stub).readTab('https://tokio.rs/');
    expect(stub.injected).toEqual([]);
  });
});
