// chat.ts -- one chat exchange (design, "Turn / Question / Answer / Citation").

import type { FolderPath } from './tree.js';
import type { Identity, Title, Url } from './values.js';

/** The user's text. */
export type Question = string;

/** A prior exchange sent as history. */
export interface Turn {
  readonly question: Question;
  readonly answer: string;
}

/** A corpus entry named by identity, with where it is filed. */
export interface EntryRef {
  readonly identity: Identity;
  readonly title: Title;
  readonly path: FolderPath;
}

/** A reference to a `CorpusEntry` identity the retrieval step returned. */
export type Citation = EntryRef;

/** The grounded reply: citations from the corpus, other URLs marked external. */
export interface Answer {
  readonly text: string;
  readonly citations: readonly Citation[];
  readonly external_urls: readonly Url[];
}
