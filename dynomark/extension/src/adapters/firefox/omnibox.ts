// omnibox.ts -- the address-bar keyword `bm` on Firefox's browser.omnibox
// (task-032): the shared omnibox adapter with a plain-text dialect. Firefox
// shows a description as written, so Chrome's XML markup and entity escapes
// would print literally; here a hit is its title, folder path and identity
// joined by ` -- `, and nothing is escaped.

import type { Hit } from '../../domain/search.js';
import { listenOmnibox, type OmniboxApi, type OmniboxDialect, type OmniboxHandlers } from '../chrome/omnibox.js';

// --- Constants ---

const SEPARATOR = ' -- ';

// --- Pure helpers ---

/** The suggestion text for a hit: title, folder path, identity. */
export function describePlainHit(hit: Hit): string {
  return [hit.title, hit.path.names.join(' / '), hit.identity].join(SEPARATOR);
}

const PLAIN_DIALECT: OmniboxDialect = {
  hit: describePlainHit,
  ask: (question) => `Ask: ${question}`,
  searchDefault: 'Search Dynomark bookmarks',
  askDefault: 'Ask Dynomark',
};

// --- Entry ---

/** Wire the omnibox keyword to the background's handlers, in plain text. */
export function listenFirefoxOmnibox(handlers: OmniboxHandlers, api: OmniboxApi): void {
  listenOmnibox(handlers, api, PLAIN_DIALECT);
}
