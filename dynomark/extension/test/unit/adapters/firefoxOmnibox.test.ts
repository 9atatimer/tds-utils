// firefoxOmnibox.test.ts -- the `bm` keyword on Firefox's browser.omnibox
// (task-032). Firefox shows a suggestion's description as plain text: Chrome's
// XML dialect (<match>, <dim>, <url>, entity escapes) would appear literally,
// so every description, the default row's included, is plain text with
// nothing escaped. What a row does is unchanged: the content is the hit's
// identity, the Ask row comes last, and the default row says Ask when there
// is no hit.

import { describe, expect, it } from 'vitest';
import type { OmniboxSuggestion } from '../../../src/adapters/chrome/omnibox.js';
import { describePlainHit, listenFirefoxOmnibox } from '../../../src/adapters/firefox/omnibox.js';
import { askRowContent } from '../../../src/domain/omnibox.js';
import type { Hit } from '../../../src/domain/search.js';
import { EventStub } from '../../stubs/chromeEvents.js';

// --- Builders ---

const HIT: Hit = {
  identity: 'https://example.com/?a=1&b=<2>',
  title: 'Q&A <tips> "quoted"',
  path: { root: 'bar', names: ['Dynomark', 'R&D'] },
  score: 0.9,
  tier: 'local',
};

function omniboxApi() {
  const defaults: string[] = [];
  return {
    defaults,
    onInputChanged: new EventStub<[string, (suggestions: OmniboxSuggestion[]) => void]>(),
    onInputEntered: new EventStub<[string, 'currentTab' | 'newForegroundTab' | 'newBackgroundTab']>(),
    setDefaultSuggestion: (s: { description: string }) => void defaults.push(s.description),
  };
}

const MARKUP = /<\/?(?:match|dim|url)>|&(?:amp|lt|gt|quot|apos);|%s/;

// --- Tests ---

describe('Firefox omnibox suggestions', () => {
  it('Given a hit whose title and path hold markup characters, When described, Then the text is plain: title, path and identity, nothing escaped', () => {
    expect(describePlainHit(HIT)).toBe('Q&A <tips> "quoted" -- Dynomark / R&D -- https://example.com/?a=1&b=<2>');
  });

  it('Given keystrokes, When the omnibox fires, Then each row is plain text with the identity as content and the Ask row last', () => {
    const api = omniboxApi();
    listenFirefoxOmnibox(
      { input: (_text, suggest) => suggest({ hits: [HIT], ask: 'q&a', enter_asks: false }), enter: () => undefined },
      api,
    );
    const shown: OmniboxSuggestion[][] = [];
    api.onInputChanged.fire('q&a', (s) => shown.push(s));
    expect(shown).toEqual([
      [
        { content: HIT.identity, description: describePlainHit(HIT) },
        { content: askRowContent('q&a'), description: 'Ask: q&a' },
      ],
    ]);
  });

  it('Given no hit and then a hit, When the omnibox fires, Then the default row says Ask, then Search again, in plain text', () => {
    const api = omniboxApi();
    let rows = { hits: [] as Hit[], ask: 'zzz', enter_asks: true };
    listenFirefoxOmnibox({ input: (_text, suggest) => suggest(rows), enter: () => undefined }, api);
    api.onInputChanged.fire('zzz', () => undefined);
    rows = { hits: [HIT], ask: 'q', enter_asks: false };
    api.onInputChanged.fire('q', () => undefined);
    expect(api.defaults).toHaveLength(3);
    expect(api.defaults[1]).toMatch(/^Ask/);
    expect(api.defaults[2]).toBe(api.defaults[0]);
    expect(api.defaults.filter((d) => MARKUP.test(d))).toEqual([]);
  });

  it('Given Enter on a row, When the omnibox fires, Then the handler gets its content and disposition', () => {
    const api = omniboxApi();
    const entered: [string, string][] = [];
    listenFirefoxOmnibox({ input: () => undefined, enter: (text, d) => void entered.push([text, d]) }, api);
    api.onInputEntered.fire(HIT.identity, 'newForegroundTab');
    expect(entered).toEqual([[HIT.identity, 'newForegroundTab']]);
  });
});
