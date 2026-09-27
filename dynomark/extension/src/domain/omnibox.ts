// omnibox.ts -- the rows the address-bar keyword shows and what Enter does
// (design, "The extension": Tier-1 search, Tier-2 search, Ask fall-through:
// the last suggestion is always `Ask: <query>`; entering it, or entering with
// no hit, opens the chat surface with the query pre-sent).

import type { Question } from './chat.js';
import { isOpenable, type Hit, type Query } from './search.js';
import type { Identity } from './values.js';

// --- Constants ---

/** The Ask row's content starts with this; Enter on such a text asks the rest. */
export const ASK_PREFIX = 'Ask: ';

// --- Types ---

/** What the keyword shows for one keystroke: hits, then the Ask row. */
export interface OmniboxRows {
  readonly hits: readonly Hit[];
  /** The Ask row's question: always the last row; absent only for a blank query. */
  readonly ask?: Question;
  /** True when Enter on the typed text asks (there is no hit), so the default row is the Ask row. */
  readonly enter_asks: boolean;
}

/** What Enter does: open a hit's identity, ask a question in the chat surface, or nothing. */
export type EnterAction =
  | { readonly kind: 'open'; readonly identity: Identity }
  | { readonly kind: 'ask'; readonly question: Question }
  | { readonly kind: 'none' };

// --- Pure helpers ---

/** The rows for `query`: its hits, then the Ask row (none for a blank query). */
export function omniboxRows(query: Query, hits: readonly Hit[]): OmniboxRows {
  const question = query.trim();
  if (question === '') return { hits, enter_asks: false };
  return { hits, ask: question, enter_asks: hits.length === 0 };
}

/** The content of the Ask row for `question` (what Enter hands back when it is picked). */
export function askRowContent(question: Question): string {
  return `${ASK_PREFIX}${question}`;
}

function ask(text: string): EnterAction {
  const question = text.trim();
  return question === '' ? { kind: 'none' } : { kind: 'ask', question };
}

/**
 * What Enter on `text` does: the Ask row asks its question; a picked hit
 * (its content is its identity) opens; so does text that is itself an
 * http(s) URL -- a picked row's identity reaches a worker that may never have
 * shown it (the worker restarted, or the hit came from tier 2) -- and plain
 * text opens the best hit, or asks when there is none.
 */
export function enterAction(text: string, shown: readonly Hit[], best: Hit | undefined): EnterAction {
  if (text.startsWith(ASK_PREFIX)) return ask(text.slice(ASK_PREFIX.length));
  const picked = shown.find((h) => h.identity === text);
  if (picked !== undefined) return { kind: 'open', identity: picked.identity };
  const url = text.trim();
  if (isOpenable(url) && !/\s/.test(url)) return { kind: 'open', identity: url };
  if (best !== undefined) return { kind: 'open', identity: best.identity };
  return ask(text);
}
