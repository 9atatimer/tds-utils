// capture.test.ts -- design Behaviors row "Content is captured from the open
// tab": capture(bookmark, *, content) -> Capture. Given a tab showing the URL,
// When captured, Then source is tab and text is non-empty; otherwise the
// request carries source none. Security: non-http(s) URLs are never captured.
// Contract v1 "Size limits" and "Framing": text and title are cut at a code
// point boundary and made well-formed before they can reach the wire.

import { describe, expect, it } from 'vitest';
import { capture } from '../../../src/app/capture.js';
import type { Bookmark } from '../../../src/domain/tree.js';
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
