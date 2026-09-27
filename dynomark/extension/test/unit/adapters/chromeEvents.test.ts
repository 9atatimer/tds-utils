// chromeEvents.test.ts -- the browser-event adapters: chrome.bookmarks events
// become BookmarkEvents; the omnibox shows hits as XML-escaped suggestions
// whose content is the hit's identity and reports Enter with its
// disposition; the navigator opens a URL where the disposition says; pages
// and background talk over chrome.runtime messaging, answering only
// Dynomark page requests from this extension.

import { describe, expect, it } from 'vitest';
import { listenBookmarkEvents } from '../../../src/adapters/chrome/bookmarkEvents.js';
import { ChromeNavigator } from '../../../src/adapters/chrome/navigator.js';
import { describeHit, listenOmnibox, type OmniboxSuggestion } from '../../../src/adapters/chrome/omnibox.js';
import { ChromePageClient, servePages } from '../../../src/adapters/chrome/pageChannel.js';
import type { Hit } from '../../../src/domain/search.js';
import type { BookmarkEvent } from '../../../src/ports/bookmarkEvents.js';
import type { PageRequest, PageResponse } from '../../../src/ports/pages.js';
import { EventStub } from '../../stubs/chromeEvents.js';

// --- Builders ---

const HIT: Hit = {
  identity: 'https://example.com/?a=1&b=<2>',
  title: 'Q&A <tips> "quoted" \'single\'',
  path: { root: 'bar', names: ['Dynomark', 'R&D'] },
  score: 0.9,
  tier: 'local',
};

function bookmarkApi() {
  return {
    onCreated: new EventStub<
      [string, { id: string; parentId?: string; index?: number; title: string; url?: string; dateAdded?: number }]
    >(),
    onMoved: new EventStub<[string, { parentId: string; oldParentId: string; index: number; oldIndex: number }]>(),
    onChanged: new EventStub<[string, { title: string; url?: string }]>(),
    onRemoved: new EventStub<[string, { parentId: string; index: number }]>(),
    onChildrenReordered: new EventStub<[string, { childIds: string[] }]>(),
  };
}

// --- Tests ---

describe('listenBookmarkEvents', () => {
  it('Given each chrome.bookmarks event, When fired, Then the listener gets the matching BookmarkEvent', () => {
    const api = bookmarkApi();
    const seen: BookmarkEvent[] = [];
    listenBookmarkEvents((e) => seen.push(e), api);
    api.onCreated.fire('7', { id: '7', parentId: '5', index: 0, title: 'Tokio', url: 'https://tokio.rs/', dateAdded: 1_000.5 });
    api.onMoved.fire('7', { parentId: '6', oldParentId: '5', index: 0, oldIndex: 0 });
    api.onChanged.fire('7', { title: 'Tokio!' });
    api.onRemoved.fire('7', { parentId: '6', index: 0 });
    api.onChildrenReordered.fire('6', { childIds: [] });
    expect(seen).toEqual([
      {
        kind: 'created',
        node: { id: '7', parent_id: '5', index: 0, kind: 'bookmark', title: 'Tokio', url: 'https://tokio.rs/', date_added: 1_000 },
      },
      { kind: 'moved', node_id: '7', parent_id: '6', old_parent_id: '5' },
      { kind: 'changed', node_id: '7' },
      { kind: 'removed', node_id: '7', parent_id: '6' },
      { kind: 'reordered', folder_id: '6' },
    ]);
  });
});

describe('Omnibox suggestions', () => {
  it('Given a hit whose title and path hold XML metacharacters, When described, Then every one is escaped and the path is dimmed', () => {
    expect(describeHit(HIT)).toBe(
      'Q&amp;A &lt;tips&gt; &quot;quoted&quot; &apos;single&apos; <dim>Dynomark / R&amp;D</dim> <url>https://example.com/?a=1&amp;b=&lt;2&gt;</url>',
    );
  });

  it('Given keystrokes and Enter, When the omnibox fires, Then hits become suggestions with the identity as content, and Enter carries the disposition', () => {
    const api = {
      onInputChanged: new EventStub<[string, (suggestions: OmniboxSuggestion[]) => void]>(),
      onInputEntered: new EventStub<[string, 'currentTab' | 'newForegroundTab' | 'newBackgroundTab']>(),
      setDefaultSuggestion: (s: { description: string }) => void defaults.push(s.description),
    };
    const defaults: string[] = [];
    const entered: [string, string][] = [];
    listenOmnibox({ input: (_text, suggest) => suggest([HIT]), enter: (text, d) => void entered.push([text, d]) }, api);
    const shown: OmniboxSuggestion[][] = [];
    api.onInputChanged.fire('q&a', (s) => shown.push(s));
    api.onInputEntered.fire('https://example.com/?a=1&b=<2>', 'newBackgroundTab');
    expect(shown).toEqual([[{ content: HIT.identity, description: describeHit(HIT) }]]);
    expect(entered).toEqual([['https://example.com/?a=1&b=<2>', 'newBackgroundTab']]);
    expect(defaults).toHaveLength(1);
  });
});

describe('ChromeNavigator', () => {
  it('Given each disposition, When a URL is opened, Then the current tab is updated or a tab is created in the foreground or background', async () => {
    const calls: string[] = [];
    const tabs = {
      update: (p: { url: string }) => Promise.resolve(void calls.push(`update ${p.url}`)),
      create: (p: { url: string; active: boolean }) => Promise.resolve(void calls.push(`create ${p.url} active=${String(p.active)}`)),
    };
    const nav = new ChromeNavigator(tabs);
    await nav.open('https://a.example/', 'currentTab');
    await nav.open('https://b.example/', 'newForegroundTab');
    await nav.open('https://c.example/', 'newBackgroundTab');
    expect(calls).toEqual(['update https://a.example/', 'create https://b.example/ active=true', 'create https://c.example/ active=false']);
  });
});

describe('Page channel', () => {
  function runtimeApi() {
    const onMessage = new EventStub<[unknown, { id?: string }, (response: unknown) => void], boolean>();
    return {
      id: 'self-id',
      onMessage,
      sendMessage: (message: unknown): Promise<unknown> =>
        new Promise((resolve) => {
          const handled = onMessage.fire(JSON.parse(JSON.stringify(message)) as unknown, { id: 'self-id' }, resolve);
          if (!handled.some(Boolean)) resolve(undefined);
        }),
    };
  }

  it('Given a served background, When a page asks through the client, Then the answer comes back', async () => {
    const api = runtimeApi();
    const asked: PageRequest[] = [];
    servePages((request) => {
      asked.push(request);
      return Promise.resolve<PageResponse>({
        ok: true,
        kind: 'job.retry',
        job: { job_id: 'j', node_id: '1', identity: 'https://x/', state: 'QUEUED', seq: 1, attempts: 0, backfill: false },
      });
    }, api);
    const response = await new ChromePageClient(api).request({ kind: 'job.retry', job_id: 'j' });
    expect(response).toMatchObject({ ok: true, kind: 'job.retry' });
    expect(asked).toEqual([{ kind: 'job.retry', job_id: 'j' }]);
  });

  it('Given a message that is not a page request, or one from another extension, When it arrives, Then it is not answered', () => {
    const api = runtimeApi();
    servePages(() => Promise.reject(new Error('must not be asked')), api);
    const replies: unknown[] = [];
    expect(api.onMessage.fire({ hello: 'there' }, { id: 'self-id' }, (r) => replies.push(r))).toEqual([false]);
    expect(api.onMessage.fire({ dynomark_page: { kind: 'overview' } }, { id: 'other-id' }, (r) => replies.push(r))).toEqual([false]);
    expect(api.onMessage.fire({ dynomark_page: { kind: 'format-disk' } }, { id: 'self-id' }, (r) => replies.push(r))).toEqual([false]);
    expect(replies).toEqual([]);
  });

  it('Given the background has no listener, When a page asks, Then the client answers ok false instead of throwing', async () => {
    const response = await new ChromePageClient({
      id: 'x',
      sendMessage: () => Promise.reject(new Error('Receiving end does not exist.')),
    }).request({
      kind: 'overview',
    });
    expect(response).toMatchObject({ ok: false });
  });
});
