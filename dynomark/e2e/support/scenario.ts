// scenario.ts -- the pages the scenarios save and the fake-model scripts
// that file them. Each page carries one word that appears only in its body
// text (never in its title, the scripted summary or tags), so a hit on that
// word proves the captured page text was indexed (Goal 4, tier 2).

import type { FolderPath, Script } from './daemon.js';

// --- Pages ---

export const TOKIO = {
  path: '/tokio',
  title: 'Tokio tutorial',
  /** Only in the body text. */
  bodyWord: 'quokkaphile',
  html: `<!doctype html><title>Tokio tutorial</title><body><nav>Home Docs Blog</nav>
<article><h1>Tokio tutorial</h1><p>Tokio schedules tasks cooperatively, and every quokkaphile knows cancellation happens at an await point.</p></article>
<footer>Copyright</footer></body>`,
};

export const SERDE = {
  path: '/serde',
  title: 'Serde guide',
  bodyWord: 'zanzibarite',
  html: `<!doctype html><title>Serde guide</title><body>
<article><h1>Serde guide</h1><p>Serde derives serializers; a zanzibarite would call it zero-copy.</p></article></body>`,
};

export const PAGES: Readonly<Record<string, string>> = { [TOKIO.path]: TOKIO.html, [SERDE.path]: SERDE.html };

// --- Owned paths ---

export const FOLLOW_UP = ['Follow Up'];
export const DYNOMARK = ['Dynomark'];
export const READING = ['Dynomark', 'Reading'];
export const OWNED_TOP_LEVEL = ['Follow Up', 'Dynomark', 'Graveyard'];

export function bar(...names: string[]): FolderPath {
  return { root: 'bar', names };
}

// --- Scripts ---

const ENRICHMENT = { summary: 'A page saved for later reading.', tags: ['saved'] };
const READING_CHOICE = { folder: bar(...READING), rationale: 'Saved pages are read from Reading.' };

/** Enough answers to enrich and place `saves` saves (plus one retry each). */
export function filing(saves: number): Script {
  return {
    enrich: Array.from({ length: saves * 2 }, () => ENRICHMENT),
    choose_folder: Array.from({ length: saves * 2 }, () => READING_CHOICE),
  };
}

/** Enrichment only: a reader indexes and never places. */
export function indexing(saves: number): Script {
  return { enrich: Array.from({ length: saves * 2 }, () => ENRICHMENT) };
}

/** A URL outside the corpus, for an answer to mark external. */
export const EXTERNAL_URL = 'https://rust-lang.github.io/async-book/';
