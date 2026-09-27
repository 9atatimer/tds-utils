// omnibox.test.ts -- the rows the `bm` keyword shows and what Enter does
// (design, "The extension": Ask fall-through -- the last suggestion is always
// `Ask: <query>`; entering it, or entering with no hit, opens the chat surface
// with the query pre-sent).

import { describe, expect, it } from 'vitest';
import { ASK_PREFIX, askRowContent, enterAction, omniboxRows } from '../../../src/domain/omnibox.js';
import type { Hit } from '../../../src/domain/search.js';

// --- Builders ---

function hit(identity: string, title = 'T'): Hit {
  return { identity, title, path: { root: 'bar', names: ['Dynomark'] }, score: 0.9, tier: 'local' };
}

const TOKIO = hit('https://tokio.rs/', 'Tokio');
const SERDE = hit('https://serde.rs/', 'Serde');

// --- Tests ---

describe('omniboxRows -- the Ask row is always last', () => {
  it('Given hits, When the rows are built, Then the hits come first and the Ask row names the query, and Enter does not ask', () => {
    expect(omniboxRows('tokio', [TOKIO, SERDE])).toEqual({ hits: [TOKIO, SERDE], ask: 'tokio', enter_asks: false });
  });

  it('Given no hits, When the rows are built, Then the Ask row is the only row and Enter asks', () => {
    expect(omniboxRows('how do I cancel a future', [])).toEqual({ hits: [], ask: 'how do I cancel a future', enter_asks: true });
  });

  it('Given surrounding blanks, When the rows are built, Then the Ask row carries the trimmed query', () => {
    expect(omniboxRows('  tokio  ', [])).toMatchObject({ ask: 'tokio' });
  });

  it('Given a blank query, When the rows are built, Then there is no row at all and Enter does nothing', () => {
    expect(omniboxRows('   ', [])).toEqual({ hits: [], enter_asks: false });
  });

  it('Given a question, When its row content is built, Then it is the Ask prefix and the question', () => {
    expect(askRowContent('why rust')).toBe(`${ASK_PREFIX}why rust`);
  });
});

describe('enterAction -- what Enter does', () => {
  it('Given the Ask row was picked, When entered, Then the chat opens with its question', () => {
    expect(enterAction(askRowContent('why rust'), [TOKIO], TOKIO)).toEqual({ kind: 'ask', question: 'why rust' });
  });

  it('Given a hit was picked (its content is its identity), When entered, Then that identity opens, not the best hit', () => {
    expect(enterAction(SERDE.identity, [TOKIO, SERDE], TOKIO)).toEqual({ kind: 'open', identity: SERDE.identity });
  });

  it('Given plain text with a best hit, When entered, Then the best hit opens', () => {
    expect(enterAction('tok', [TOKIO], TOKIO)).toEqual({ kind: 'open', identity: TOKIO.identity });
  });

  it('Given plain text with no hit, When entered, Then the chat opens with the text as its question', () => {
    expect(enterAction('  what is pin  ', [], undefined)).toEqual({ kind: 'ask', question: 'what is pin' });
  });

  it('Given blank text, or the Ask prefix with nothing after it, When entered, Then nothing happens', () => {
    expect(enterAction('   ', [], undefined)).toEqual({ kind: 'none' });
    expect(enterAction(`${ASK_PREFIX}  `, [], undefined)).toEqual({ kind: 'none' });
  });
});
