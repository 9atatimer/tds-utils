// firefoxPorts.test.ts -- the Firefox composition (task-032): every port the
// background runtime needs, built on Firefox's `browser` namespace. The port
// contract suites run against the ports it builds, over a stand-in for that
// namespace; where Firefox's API equals Chrome's the adapter is shared, and
// where it differs the difference is tested here: a lost native host is
// reported on port.error, never on runtime.lastError.

import { describe, expect, it } from 'vitest';
import { firefoxPorts } from '../../../src/adapters/firefox/ports.js';
import { ExtensionRuntime } from '../../../src/app/runtime.js';
import type { LinkState } from '../../../src/ports/transport.js';
import { describeBookmarkTreeContract } from '../../port-contracts/bookmarkTree.contract.js';
import { describeContentSourceContract } from '../../port-contracts/contentSource.contract.js';
import { describeHistoryContract } from '../../port-contracts/history.contract.js';
import { describeStorageContract } from '../../port-contracts/storage.contract.js';
import { describeTransportContract } from '../../port-contracts/transport.contract.js';
import { fakeFirefox } from '../../stubs/firefoxBrowser.js';

// --- The port contracts, against the ports the Firefox composition builds ---

describeBookmarkTreeContract('firefoxPorts().tree (stubbed browser.bookmarks)', () => firefoxPorts(fakeFirefox().api).tree);

describeHistoryContract('firefoxPorts().history (stubbed browser.history)', () => {
  const fx = fakeFirefox();
  return { history: firefoxPorts(fx.api).history, seedVisit: (url, at) => Promise.resolve(fx.history.addVisit(url, at)) };
});

describeContentSourceContract('firefoxPorts().content (stubbed browser.tabs/scripting)', () => {
  const fx = fakeFirefox();
  return {
    content: firefoxPorts(fx.api).content,
    openTab: (url, page) => Promise.resolve(void fx.tabs.open(url, page)),
    openUnreadableTab: (url) => Promise.resolve(void fx.tabs.open(url, 'unreadable')),
  };
});

describeStorageContract('firefoxPorts().storage (stubbed browser.storage.local)', () => firefoxPorts(fakeFirefox().api).storage);

describeTransportContract('firefoxPorts().transport (stubbed browser.runtime.connectNative)', () => {
  const fx = fakeFirefox();
  return { transport: firefoxPorts(fx.api).transport, daemon: fx.native.daemon };
});

// --- Firefox's own behaviour ---

describe('firefoxPorts', () => {
  it('Given every port built on the browser namespace, When the runtime is composed over them, Then it builds', () => {
    expect(new ExtensionRuntime(firefoxPorts(fakeFirefox().api))).toBeInstanceOf(ExtensionRuntime);
  });

  it('Given the native host fails, When Firefox disconnects the port with port.error set, Then the link is disconnected with that message as detail', async () => {
    const fx = fakeFirefox();
    const { transport } = firefoxPorts(fx.api);
    const states: LinkState[] = [];
    transport.onLink((s) => states.push(s));
    const lost = transport.send({ v: 1, type: 'status', id: 'req-1' });
    await fx.native.daemon.nextRequest();
    fx.native.exit('No such native application tds.dynomark');
    await expect(lost).rejects.toMatchObject({ reason: 'disconnected' });
    expect(states.at(-1)).toEqual({ state: 'disconnected', detail: 'No such native application tds.dynomark' });
  });

  it('Given no host name, When the first request is sent, Then the browser connects to tds.dynomark', async () => {
    const fx = fakeFirefox();
    void firefoxPorts(fx.api).transport.send({ v: 1, type: 'status', id: 'req-1' });
    await fx.native.daemon.nextRequest();
    expect(fx.native.connects).toEqual(['tds.dynomark']);
  });

  it('Given a page that loads, When the background-tab port reads it, Then an unfocused minimized window opens on it, is read and closes', async () => {
    const fx = fakeFirefox();
    const { background } = firefoxPorts(fx.api);
    fx.windows.serve('https://news.example/story', { title: 'Story', text: 'Signed-in text.' });
    expect(await background.readTab('https://news.example/story')).toEqual({ title: 'Story', text: 'Signed-in text.' });
    expect(fx.windows.log).toEqual([
      'open https://news.example/story focused=false state=minimized',
      'inject https://news.example/story',
      'close https://news.example/story',
    ]);
  });

  it('Given an omnibox choice, When the navigator opens it, Then the tab is navigated or opened as the disposition says', async () => {
    const fx = fakeFirefox();
    const { navigator } = firefoxPorts(fx.api);
    await navigator.open('https://tokio.rs/', 'currentTab');
    await navigator.open('https://serde.rs/', 'newBackgroundTab');
    expect(fx.opened).toEqual(['update https://tokio.rs/', 'create https://serde.rs/ active=false']);
  });
});
