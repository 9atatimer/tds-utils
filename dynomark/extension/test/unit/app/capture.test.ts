// capture.test.ts -- design Behaviors row "Content is captured from the open
// tab": capture(bookmark, *, content) -> Capture. Given a tab showing the URL,
// When captured, Then source is tab and text is non-empty; otherwise the
// request carries source none. Security: non-http(s) URLs are never captured.
// Contract v2 "Size limits" and "Framing": text and title are cut at a code
// point boundary and made well-formed before they can reach the wire.
// Background-tab capture (design, Future Considerations, MVP; task-031): when
// the chain has a background adapter, a URL no tab shows is opened in a
// background tab and captured with source background_tab; the chain is
// matching tab -> background tab -> none (the daemon then fetches).

import { describe, expect, it } from 'vitest';
import { capture } from '../../../src/app/capture.js';
import type { Bookmark } from '../../../src/domain/tree.js';
import { TransportLost } from '../../../src/ports/transport.js';
import { FakeBackgroundTabs } from '../../fakes/FakeBackgroundTabs.js';
import { FakeTabs } from '../../fakes/FakeTabs.js';

// --- Builders ---

function bookmark(url: string): Bookmark {
  return { node_id: '42', url, title: 'Tokio tutorial', path: { root: 'bar', names: ['Follow Up'] }, date_added: 1_790_000_000_000 };
}

/** A ContentSourcePort that fails the test if it is ever asked. */
const NEVER_ASKED = {
  readTab: (url: string) => Promise.reject(new Error(`readTab(${url}) must not be called`)),
};

/** A literal loopback, private or link-local host: what the daemon's default address policy refuses here. */
const PRIVATE_LITERAL = /^https?:\/\/(127\.|10\.|192\.168\.|169\.254\.|\[::1\]|localhost[:/])/;

/** The daemon's url.vet: private literals refused unless `privateAddresses` (the opt-out), and any URL in `refuse`. */
function policy(options: { readonly privateAddresses?: boolean; readonly refuse?: readonly string[]; readonly asked?: string[] } = {}) {
  return (url: string) => {
    options.asked?.push(url);
    if (options.refuse?.includes(url)) return Promise.resolve(false);
    return Promise.resolve(options.privateAddresses === true || !PRIVATE_LITERAL.test(url));
  };
}

/** A vet the daemon allows, recording each URL it was asked about. */
function allowing(asked: string[] = []) {
  return (url: string) => {
    asked.push(url);
    return Promise.resolve(true);
  };
}

// --- Tests ---

describe('Behavior: Content is captured from the open tab -- capture(bookmark, { content })', () => {
  it('Given a tab showing the saved URL, When captured, Then source is tab, text is the readable text and the title is the page title', async () => {
    const tabs = new FakeTabs();
    tabs.open('https://tokio.rs/tokio/tutorial', { title: 'Tutorial | Tokio', text: 'Tokio is an asynchronous runtime for Rust.' });
    const result = await capture(bookmark('https://tokio.rs/tokio/tutorial'), { content: tabs });
    expect(result).toEqual({ source: 'tab', text: 'Tokio is an asynchronous runtime for Rust.', title: 'Tutorial | Tokio' });
  });

  it('Given no tab shows the saved URL, When captured, Then source is none with empty text', async () => {
    const tabs = new FakeTabs();
    tabs.open('https://tokio.rs/', { title: 'Tokio', text: 'home page' });
    expect(await capture(bookmark('https://tokio.rs/tokio/tutorial'), { content: tabs })).toEqual({ source: 'none', text: '' });
  });

  it('Given a tab that cannot be read, When captured, Then source is none', async () => {
    const tabs = new FakeTabs();
    tabs.open('https://tokio.rs/tokio/tutorial', 'unreadable');
    expect(await capture(bookmark('https://tokio.rs/tokio/tutorial'), { content: tabs })).toEqual({ source: 'none', text: '' });
  });

  it('Given a tab whose readable text is only whitespace, When captured, Then it is no capture (source none), never an empty tab capture', async () => {
    const tabs = new FakeTabs();
    tabs.open('https://tokio.rs/tokio/tutorial', { title: 'Tokio', text: ' \n\t ' });
    expect(await capture(bookmark('https://tokio.rs/tokio/tutorial'), { content: tabs })).toEqual({ source: 'none', text: '' });
  });

  it.each(['file:///home/me/notes.html', 'chrome://settings/', 'javascript:alert(1)', 'about:blank'])(
    'Given the non-http(s) URL %s, When captured, Then source is none and no tab is ever read (design, Security)',
    async (url) => {
      expect(await capture(bookmark(url), { content: NEVER_ASKED })).toEqual({ source: 'none', text: '' });
    },
  );

  it('Given text over 1,048,576 code points ending in astral characters, When captured, Then it is cut to exactly the cap at a code point boundary', async () => {
    const tabs = new FakeTabs();
    const text = 'a'.repeat(1_048_575) + '\u{1F980}\u{1F980}';
    tabs.open('https://tokio.rs/', { title: 'Tokio', text });
    const result = await capture(bookmark('https://tokio.rs/'), { content: tabs });
    expect([...result.text].length).toBe(1_048_576);
    expect(result.text.endsWith('a\u{1F980}')).toBe(true);
  });

  it('Given a page title over 4,096 code points holding a lone surrogate, When captured, Then the title is well-formed and cut to the cap', async () => {
    const tabs = new FakeTabs();
    tabs.open('https://tokio.rs/', { title: '\uD83E' + 'b'.repeat(5000), text: 'body' });
    const result = await capture(bookmark('https://tokio.rs/'), { content: tabs });
    expect(result.title).toBe('�' + 'b'.repeat(4095));
  });
});

describe('Background-tab capture -- the chain: matching tab, then background tab, then none', () => {
  const URL = 'https://news.example/paywalled/story';
  const PAGE = { title: 'Story', text: 'Full text visible only when signed in.' };

  it('Given a tab shows the URL, When captured with a background adapter, Then the tab is read and no background tab is opened', async () => {
    const tabs = new FakeTabs();
    tabs.open(URL, PAGE);
    const background = new FakeBackgroundTabs();
    const asked: string[] = [];
    expect(await capture(bookmark(URL), { content: tabs, background: { tabs: background, vet: allowing(asked) } })).toMatchObject({
      source: 'tab',
    });
    expect(background.opened).toEqual([]);
    expect(asked).toEqual([]);
  });

  it('Given no tab shows the URL, When captured with a background adapter, Then it is opened in the background and the capture has source background_tab', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    const asked: string[] = [];
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: allowing(asked) } })).toEqual({
      source: 'background_tab',
      ...PAGE,
    });
    expect(asked[0]).toBe(URL);
    expect(background.opened).toEqual([URL]);
  });

  it('Given an open tab with no readable text, When captured with a background adapter, Then the background tab is tried', async () => {
    const tabs = new FakeTabs();
    tabs.open(URL, { title: 'Story', text: '  ' });
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    expect(await capture(bookmark(URL), { content: tabs, background: { tabs: background, vet: allowing() } })).toMatchObject({
      source: 'background_tab',
    });
  });

  it('Given the background tab cannot be read either, When captured, Then source is none', async () => {
    expect(
      await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: new FakeBackgroundTabs(), vet: allowing() } }),
    ).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given a non-http(s) URL, When captured with a background adapter, Then nothing is opened', async () => {
    const vet = (url: string) => Promise.reject(new Error(`vet(${url}) must not be called`));
    expect(await capture(bookmark('file:///etc/passwd'), { content: NEVER_ASKED, background: { tabs: NEVER_ASKED, vet } })).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given the daemon refuses the URL (url.vet allowed false: a loopback, private or link-local address), When captured, Then source is none and no background tab is opened (issue #410)', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    const refused = () => Promise.resolve(false);
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: refused } })).toEqual({
      source: 'none',
      text: '',
    });
    expect(background.opened).toEqual([]);
  });

  it('Given the vet cannot be answered (the daemon is down: the request is lost), When captured, Then source is none and no background tab is opened (issue #410)', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    const lost = () => Promise.reject(new TransportLost('disconnected'));
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: lost } })).toEqual({
      source: 'none',
      text: '',
    });
    expect(background.opened).toEqual([]);
  });
});

describe('Background-tab capture -- the page is held to the address policy where the load ended (issue #534)', () => {
  const URL = 'https://news.example/paywalled/story';
  const PRIVATE = 'http://10.0.0.5/admin';
  const SECRET = { title: 'Router admin', text: 'WAN password: hunter2' };

  function redirected(to: string, page = SECRET): FakeBackgroundTabs {
    const background = new FakeBackgroundTabs();
    background.redirect(URL, to);
    background.serve(to, page);
    return background;
  }

  it('Given a vetted URL whose background load is redirected to a private address, When captured, Then source is none and the private page text is not captured', async () => {
    const background = redirected(PRIVATE);
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: policy() } })).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given a vetted URL redirected to a URL the daemon refuses (a host that resolves to a private address), When captured, Then source is none', async () => {
    const elsewhere = 'https://intranet.example.com/wiki';
    const background = redirected(elsewhere);
    const vet = policy({ refuse: [elsewhere] });
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet } })).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given a vetted URL redirected elsewhere, When the vet of where it ended cannot be answered (the link is lost), Then source is none', async () => {
    const elsewhere = 'https://other.example/story';
    const background = redirected(elsewhere);
    const vet = (url: string) => (url === elsewhere ? Promise.reject(new TransportLost('disconnected')) : Promise.resolve(true));
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet } })).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given a vetted URL redirected to another URL the daemon allows, When captured, Then the daemon was asked about where it ended and the capture is background_tab', async () => {
    const elsewhere = 'https://news.example/story?from=paywall';
    const page = { title: 'Story', text: 'Full text.' };
    const background = redirected(elsewhere, page);
    const asked: string[] = [];
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: policy({ asked }) } })).toEqual({
      source: 'background_tab',
      ...page,
    });
    expect(asked).toContain(elsewhere);
  });

  it('Given the daemon refuses private addresses (its default policy), When the background tab loads, Then it is told to block private hosts', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, { title: 'Story', text: 'Full text.' });
    await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet: policy() } });
    expect(background.loads).toEqual([{ url: URL, blockPrivateHosts: true }]);
  });

  it('Given the daemon allows private addresses (the opt-out, for fetch and background tab alike), When a load is redirected to one, Then nothing is blocked and it is captured', async () => {
    const background = redirected(PRIVATE);
    const vet = policy({ privateAddresses: true });
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet } })).toEqual({
      source: 'background_tab',
      ...SECRET,
    });
    expect(background.loads).toEqual([{ url: URL, blockPrivateHosts: false }]);
  });

  it('Given the check of the policy cannot be answered after the URL was vetted, When the background tab loads, Then private hosts are blocked', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, { title: 'Story', text: 'Full text.' });
    const vet = (url: string) => (url === URL ? Promise.resolve(true) : Promise.reject(new TransportLost('disconnected')));
    await capture(bookmark(URL), { content: new FakeTabs(), background: { tabs: background, vet } });
    expect(background.loads.map((l) => l.blockPrivateHosts)).toEqual([true]);
  });
});
