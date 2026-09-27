// capture.test.ts -- design Behaviors row "Content is captured from the open
// tab": capture(bookmark, *, content) -> Capture. Given a tab showing the URL,
// When captured, Then source is tab and text is non-empty; otherwise the
// request carries source none. Security: non-http(s) URLs are never captured.
// Contract v1 "Size limits" and "Framing": text and title are cut at a code
// point boundary and made well-formed before they can reach the wire.
// Background-tab capture (design, Future Considerations, MVP; task-031): when
// the chain has a background adapter, a URL no tab shows is opened in a
// background tab and captured with source background_tab; the chain is
// matching tab -> background tab -> none (the daemon then fetches).

import { describe, expect, it } from 'vitest';
import { capture } from '../../../src/app/capture.js';
import type { Bookmark } from '../../../src/domain/tree.js';
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
    expect(await capture(bookmark(URL), { content: tabs, background })).toMatchObject({ source: 'tab' });
    expect(background.opened).toEqual([]);
  });

  it('Given no tab shows the URL, When captured with a background adapter, Then it is opened in the background and the capture has source background_tab', async () => {
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background })).toEqual({ source: 'background_tab', ...PAGE });
    expect(background.opened).toEqual([URL]);
  });

  it('Given an open tab with no readable text, When captured with a background adapter, Then the background tab is tried', async () => {
    const tabs = new FakeTabs();
    tabs.open(URL, { title: 'Story', text: '  ' });
    const background = new FakeBackgroundTabs();
    background.serve(URL, PAGE);
    expect(await capture(bookmark(URL), { content: tabs, background })).toMatchObject({ source: 'background_tab' });
  });

  it('Given the background tab cannot be read either, When captured, Then source is none', async () => {
    expect(await capture(bookmark(URL), { content: new FakeTabs(), background: new FakeBackgroundTabs() })).toEqual({
      source: 'none',
      text: '',
    });
  });

  it('Given a non-http(s) URL, When captured with a background adapter, Then nothing is opened', async () => {
    expect(await capture(bookmark('file:///etc/passwd'), { content: NEVER_ASKED, background: NEVER_ASKED })).toEqual({
      source: 'none',
      text: '',
    });
  });
});
