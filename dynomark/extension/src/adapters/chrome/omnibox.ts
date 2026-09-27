/// <reference types="chrome" />
// omnibox.ts -- the address-bar keyword `bm` on chrome.omnibox (manifest
// "omnibox.keyword"; design, "The extension", Tier-1 and Tier-2 search). A
// hit becomes a suggestion whose content is its identity (Enter hands the
// content back) and whose description is Chrome's small XML dialect, every
// daemon-supplied string escaped.

import type { Hit } from '../../domain/search.js';
import type { Disposition } from '../../ports/navigator.js';

// --- Types ---

export interface OmniboxSuggestion {
  readonly content: string;
  readonly description: string;
}

/** What the background does with the omnibox. */
export interface OmniboxHandlers {
  input(text: string, suggest: (hits: readonly Hit[]) => void): void;
  enter(text: string, disposition: Disposition): void;
}

interface EventLike<A extends unknown[]> {
  addListener(callback: (...args: A) => void): void;
}

/** The part of chrome.omnibox this adapter uses. */
export interface OmniboxApi {
  readonly onInputChanged: EventLike<[string, (suggestions: OmniboxSuggestion[]) => void]>;
  readonly onInputEntered: EventLike<[string, Disposition]>;
  setDefaultSuggestion(suggestion: { description: string }): void;
}

// --- Constants ---

const XML_ESCAPES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
const DEFAULT_DESCRIPTION = 'Search Dynomark bookmarks for <match>%s</match>';

// --- Pure helpers ---

function escapeXml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => XML_ESCAPES[c] ?? c);
}

/** The suggestion text for a hit: title, then its folder path dimmed, then its identity as a URL. */
export function describeHit(hit: Hit): string {
  return `${escapeXml(hit.title)} <dim>${escapeXml(hit.path.names.join(' / '))}</dim> <url>${escapeXml(hit.identity)}</url>`;
}

function toSuggestion(hit: Hit): OmniboxSuggestion {
  return { content: hit.identity, description: describeHit(hit) };
}

// --- Entry ---

/** Wire the omnibox keyword to the background's handlers. */
export function listenOmnibox(handlers: OmniboxHandlers, api: OmniboxApi = chrome.omnibox): void {
  api.setDefaultSuggestion({ description: DEFAULT_DESCRIPTION });
  api.onInputChanged.addListener((text, suggest) => handlers.input(text, (hits) => suggest(hits.map(toSuggestion))));
  api.onInputEntered.addListener((text, disposition) => handlers.enter(text, disposition));
}
