// limits.ts -- the contract's caps on browser data, and the one rule for
// meeting them (contract v1 README, "Size limits" and "Framing"): strings are
// made well-formed, then cut at a code point boundary, never mid-pair.

import { toWellFormed } from './text.js';
import type { Bookmark, FolderPath } from './tree.js';

// --- Constants ---

/** `Title`, `SnapshotNode.title`: code points. */
export const MAX_TITLE = 4096;
/** `Url`, `Identity`, `SnapshotNode.url`: code points. */
export const MAX_URL = 65_536;
/** `Capture.text`: code points. */
export const MAX_CAPTURE_TEXT = 1_048_576;
/** `search.query`: code points. */
export const MAX_QUERY = 1024;
/** Free-text `detail` and `message` fields: code points. */
export const MAX_DETAIL = 4096;
/** A `LocalIndexRow` as compact UTF-8 JSON: bytes. */
export const MAX_INDEX_ROW_BYTES = 512;

// --- Types ---

/** A well-formed string within its cap, and whether it had to be cut. */
export interface Fitted {
  readonly text: string;
  readonly truncated: boolean;
}

// --- Pure helpers ---

/** The first `max` code points of `s`; `s` itself when it already fits. */
export function truncateCodePoints(s: string, max: number): Fitted {
  if (s.length <= max) return { text: s, truncated: false };
  let units = 0;
  let points = 0;
  for (const ch of s) {
    if (points === max) return { text: s.slice(0, units), truncated: true };
    units += ch.length;
    points += 1;
  }
  return { text: s, truncated: false };
}

/** `s` made well-formed (lone surrogates -> U+FFFD), then cut to `max` code points. */
export function fitText(s: string, max: number): Fitted {
  return truncateCodePoints(toWellFormed(s), max);
}

// --- Bookmarks ---

/** A FolderPath with every name well-formed and within the title cap. */
export function fitPath(path: FolderPath): FolderPath {
  return { root: path.root, names: path.names.map((name) => fitText(name, MAX_TITLE).text) };
}

/** The bookmark as it may be sent: well-formed, title and folder names cut to the cap; undefined when its url is over the cap (it is not ingested). */
export function fitBookmark(bookmark: Bookmark): Bookmark | undefined {
  const url = fitText(bookmark.url, MAX_URL);
  if (url.truncated) return undefined;
  return { ...bookmark, url: url.text, title: fitText(bookmark.title, MAX_TITLE).text, path: fitPath(bookmark.path) };
}
