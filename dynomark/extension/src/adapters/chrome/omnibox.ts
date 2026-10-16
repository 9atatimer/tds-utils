/// <reference types="chrome" />
// omnibox.ts -- the address-bar keyword `bm` on chrome.omnibox (manifest
// "omnibox.keyword"; design, "The extension", Tier-1 and Tier-2 search, Ask
// fall-through). A hit becomes a suggestion whose content is its identity
// (Enter hands the content back) and whose description is Chrome's small XML
// dialect, every daemon-supplied string escaped; the Ask row comes last. The
// default row (the typed text itself) says Ask when there is no hit, because
// Enter on it then asks. Firefox's omnibox is the same API but shows
// descriptions as plain text; it passes its own OmniboxDialect
// (adapters/firefox/omnibox.ts).

import { askRowContent, type OmniboxRows } from '../../domain/omnibox.js';
import type { Hit } from '../../domain/search.js';
import type { Disposition } from '../../ports/navigator.js';

// --- Types ---

export interface OmniboxSuggestion {
  readonly content: string;
  readonly description: string;
}

/** What the background does with the omnibox. */
export interface OmniboxHandlers {
  input(text: string, suggest: (rows: OmniboxRows) => void): void;
  enter(text: string, disposition: Disposition): void;
}

interface EventLike<A extends unknown[]> {
  addListener(callback: (...args: A) => void): void;
}

/** How a browser's omnibox writes a row's description. */
export interface OmniboxDialect {
  hit(hit: Hit): string;
  ask(question: string): string;
  /** The default row while Enter searches. */
  readonly searchDefault: string;
  /** The default row while Enter asks. */
  readonly askDefault: string;
}

/** The part of chrome.omnibox this adapter uses. */
export interface OmniboxApi {
  readonly onInputChanged: EventLike<[string, (suggestions: OmniboxSuggestion[]) => void]>;
  readonly onInputEntered: EventLike<[string, Disposition]>;
  setDefaultSuggestion(suggestion: { description: string }): void;
}

// --- Constants ---

const XML_ESCAPES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
const SEARCH_DESCRIPTION = 'Search Dynomark bookmarks for <match>%s</match>';
const ASK_DESCRIPTION = 'Ask: <match>%s</match>';

// --- Pure helpers ---

function escapeXml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => XML_ESCAPES[c] ?? c);
}

/** The suggestion text for a hit: title, then its folder path dimmed, then its identity as a URL. */
export function describeHit(hit: Hit): string {
  return `${escapeXml(hit.title)} <dim>${escapeXml(hit.path.names.join(' / '))}</dim> <url>${escapeXml(hit.identity)}</url>`;
}

/** The Ask row's text: the question, escaped and highlighted. */
export function describeAsk(question: string): string {
  return `Ask: <match>${escapeXml(question)}</match>`;
}

/** Chrome's dialect: its small XML markup, every daemon-supplied string escaped. */
export const XML_DIALECT: OmniboxDialect = {
  hit: describeHit,
  ask: describeAsk,
  searchDefault: SEARCH_DESCRIPTION,
  askDefault: ASK_DESCRIPTION,
};

function toSuggestions(rows: OmniboxRows, dialect: OmniboxDialect): OmniboxSuggestion[] {
  const hits = rows.hits.map((hit) => ({ content: hit.identity, description: dialect.hit(hit) }));
  return rows.ask === undefined ? hits : [...hits, { content: askRowContent(rows.ask), description: dialect.ask(rows.ask) }];
}

// --- Entry ---

/** Wire the omnibox keyword to the background's handlers, writing rows in `dialect`. */
export function listenOmnibox(handlers: OmniboxHandlers, api: OmniboxApi = chrome.omnibox, dialect: OmniboxDialect = XML_DIALECT): void {
  let asking = false;
  api.setDefaultSuggestion({ description: dialect.searchDefault });
  api.onInputChanged.addListener((text, suggest) =>
    handlers.input(text, (rows) => {
      if (rows.enter_asks !== asking) {
        asking = rows.enter_asks;
        api.setDefaultSuggestion({ description: asking ? dialect.askDefault : dialect.searchDefault });
      }
      suggest(toSuggestions(rows, dialect));
    }),
  );
  api.onInputEntered.addListener((text, disposition) => handlers.enter(text, disposition));
}
