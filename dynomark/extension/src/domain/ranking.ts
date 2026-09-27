// ranking.ts -- tier-1 ranking over the LocalIndex (design, "The extension",
// Tier-1 search): title matches form a hard tier above path, tag and summary
// matches; within a tier, fuzzy score (plus the owned-item bonus) then
// frecency. Pure: values in, hits out; the use case adds nothing but a name.

import { isPathInside } from './paths.js';
import type { Frecency, Hit, LocalIndexRow, Query } from './search.js';
import { toWellFormed } from './text.js';
import type { OwnedRoots } from './tree.js';

// --- Constants ---

/** Added to the fuzzy score of an entry filed under `owned_roots.dynomark`; never lifts it out of its tier. */
export const OWNED_BONUS = 0.05;
/** How many tier-1 hits a query returns unless told otherwise. */
export const DEFAULT_TIER1_LIMIT = 50;

const SCORE_EXACT = 1;
const SCORE_PREFIX = 0.9;
const SCORE_WORD_START = 0.8;
const SCORE_SUBSTRING = 0.7;
const SCORE_SUBSEQUENCE_MIN = 0.3;
const SCORE_SUBSEQUENCE_RANGE = 0.3;
/** A subsequence match counts only when its span is at most this many times the token's length. */
const SUBSEQUENCE_MAX_SPREAD = 4;

const TITLE_TIER = 0;
const OTHER_TIER = 1;

const SEARCHABLE = new WeakMap<LocalIndexRow, Searchable>();

// --- Types ---

export interface Tier1Options {
  /** The connection's owned roots; entries under `dynomark` get OWNED_BONUS. No bonus without them. */
  readonly owned_roots?: OwnedRoots;
  readonly limit?: number;
}

interface Ranked {
  readonly row: LocalIndexRow;
  readonly tier: number;
  readonly score: number;
  readonly frecency: number;
}

interface Searchable {
  readonly title: string;
  readonly path: string;
  readonly tags: string;
  readonly summary: string;
}

// --- Predicates ---

function isWordChar(code: number): boolean {
  return (code >= 48 && code <= 57) || (code >= 97 && code <= 122) || code > 127;
}

// --- Pure helpers: fuzzy score of one token against one lower-cased field ---

function occurrenceScore(token: string, field: string): number {
  let at = field.indexOf(token);
  if (at === -1) return 0;
  if (at === 0) return field.length === token.length ? SCORE_EXACT : SCORE_PREFIX;
  while (at !== -1) {
    if (!isWordChar(field.charCodeAt(at - 1))) return SCORE_WORD_START;
    at = field.indexOf(token, at + 1);
  }
  return SCORE_SUBSTRING;
}

function subsequenceScore(token: string, field: string): number {
  let t = 0;
  let start = -1;
  let end = -1;
  for (let i = 0; i < field.length && t < token.length; i += 1) {
    if (field.charCodeAt(i) !== token.charCodeAt(t)) continue;
    if (t === 0) start = i;
    end = i;
    t += 1;
  }
  const span = end - start + 1;
  if (t < token.length || span > token.length * SUBSEQUENCE_MAX_SPREAD) return 0;
  return SCORE_SUBSEQUENCE_MIN + SCORE_SUBSEQUENCE_RANGE * (token.length / span);
}

/** Substring matches score by position; a loose subsequence counts only where `fuzzy` (titles and paths, not prose). */
function tokenScore(token: string, field: string, fuzzy: boolean): number {
  const direct = occurrenceScore(token, field);
  return direct > 0 || !fuzzy ? direct : subsequenceScore(token, field);
}

/** The mean token score when every token matches `field`, else 0. */
function fieldScore(tokens: readonly string[], field: string): number {
  let sum = 0;
  for (const token of tokens) {
    const s = tokenScore(token, field, true);
    if (s === 0) return 0;
    sum += s;
  }
  return sum / tokens.length;
}

/** The mean over tokens of each token's best score across title, path, tags and summary, when every token matches somewhere; else 0. */
function spreadScore(tokens: readonly string[], row: Searchable): number {
  let sum = 0;
  for (const token of tokens) {
    let best = Math.max(tokenScore(token, row.title, true), tokenScore(token, row.path, true));
    if (best < SCORE_EXACT) best = Math.max(best, tokenScore(token, row.tags, false), tokenScore(token, row.summary, false));
    if (best === 0) return 0;
    sum += best;
  }
  return sum / tokens.length;
}

/**
 * The row's fields lower-cased for matching. Memoized per row object: a
 * LocalIndex is loaded once and searched on every keystroke, and its rows are
 * immutable values, so the cache cannot change any result.
 */
function searchable(row: LocalIndexRow): Searchable {
  let s = SEARCHABLE.get(row);
  if (s === undefined) {
    s = {
      title: row.title.toLowerCase(),
      path: row.path.names.join(' ').toLowerCase(),
      tags: row.tags.join(' ').toLowerCase(),
      summary: row.summary.toLowerCase(),
    };
    SEARCHABLE.set(row, s);
  }
  return s;
}

/** The query's lower-cased, well-formed words. */
export function queryTokens(query: Query): string[] {
  return toWellFormed(query)
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t !== '');
}

function rankRow(tokens: readonly string[], row: LocalIndexRow, frecency: Frecency, roots: OwnedRoots | undefined): Ranked | undefined {
  const fields = searchable(row);
  const inTitle = fieldScore(tokens, fields.title);
  const tier = inTitle > 0 ? TITLE_TIER : OTHER_TIER;
  const fuzzy = inTitle > 0 ? inTitle : spreadScore(tokens, fields);
  if (fuzzy === 0) return undefined;
  const bonus = roots !== undefined && isPathInside(row.path, roots.dynomark) ? OWNED_BONUS : 0;
  return { row, tier, score: Math.min(1, fuzzy + bonus), frecency: frecency.get(row.identity) ?? 0 };
}

function compareRanked(a: Ranked, b: Ranked): number {
  if (a.tier !== b.tier) return a.tier - b.tier;
  if (a.score !== b.score) return b.score - a.score;
  if (a.frecency !== b.frecency) return b.frecency - a.frecency;
  if (a.row.title !== b.row.title) return a.row.title < b.row.title ? -1 : 1;
  return a.row.identity < b.row.identity ? -1 : a.row.identity > b.row.identity ? 1 : 0;
}

function toHit(r: Ranked): Hit {
  return { identity: r.row.identity, title: r.row.title, path: r.row.path, score: r.score, tier: 'local' };
}

/** Tier-1 hits for the query: title tier first, then by score, then frecency; at most `limit`. */
export function rankLocal(query: Query, index: readonly LocalIndexRow[], frecency: Frecency, options: Tier1Options = {}): Hit[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return [];
  const ranked: Ranked[] = [];
  for (const row of index) {
    const r = rankRow(tokens, row, frecency, options.owned_roots);
    if (r !== undefined) ranked.push(r);
  }
  return ranked
    .sort(compareRanked)
    .slice(0, options.limit ?? DEFAULT_TIER1_LIMIT)
    .map(toHit);
}
