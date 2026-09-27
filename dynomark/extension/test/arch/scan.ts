// scan.ts -- the source scanner behind the mechanical architecture tests.
//
// Pure string functions (so the guard itself is testable on synthetic input)
// plus one effectful walk of src/. Comments are blanked before scanning so a
// doc comment may name a browser API; string and template literals are kept,
// so a browser API spelled inside a string still counts.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

// --- Constants ---

/** A property access on the browser extension globals: `chrome.x`, `browser?.x`, `chrome['x']`. */
const BROWSER_GLOBAL = /\b(?:chrome|browser)\b\s*(?:\?\.|\.|\[)/;
/** A triple-slash directive pulling in browser extension ambient types. */
const BROWSER_TYPES_DIRECTIVE = /\/\/\/\s*<reference\s+types\s*=\s*["'](?:chrome|firefox-webext-browser)["']/;
const IMPORT_FROM = /\b(?:import|export)\b[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]/g;
const IMPORT_BARE = /\bimport\s*['"]([^'"]+)['"]/g;
const IMPORT_DYNAMIC = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;

// --- Predicates ---

/** True when the source (comments ignored) touches a browser extension global or its ambient types. */
export function referencesBrowserApi(source: string): boolean {
  return BROWSER_GLOBAL.test(stripComments(source)) || BROWSER_TYPES_DIRECTIVE.test(source);
}

// --- Pure helpers ---

/** Blank out // and block comments, leaving string and template literals intact. */
export function stripComments(source: string): string {
  let out = '';
  let i = 0;
  let quote: string | undefined;
  while (i < source.length) {
    const c = source[i] ?? '';
    const next = source[i + 1] ?? '';
    if (quote !== undefined) {
      out += c;
      if (c === '\\') {
        out += next;
        i += 2;
        continue;
      }
      if (c === quote) quote = undefined;
      i += 1;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      quote = c;
      out += c;
      i += 1;
      continue;
    }
    if (c === '/' && next === '/') {
      while (i < source.length && source[i] !== '\n') i += 1;
      continue;
    }
    if (c === '/' && next === '*') {
      const end = source.indexOf('*/', i + 2);
      i = end === -1 ? source.length : end + 2;
      out += ' ';
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

/** Every module specifier the source imports or re-exports (static, side-effect and dynamic). */
export function importSpecifiers(source: string): string[] {
  const code = stripComments(source);
  return [IMPORT_FROM, IMPORT_BARE, IMPORT_DYNAMIC].flatMap((re) => [...code.matchAll(re)].map((m) => m[1] ?? ''));
}

/** The first path segment under src/ that a relative specifier in `fromFile` points into, or the package name. */
export function importTarget(fromFile: string, specifier: string): string {
  if (!specifier.startsWith('.')) return specifier.split('/')[0] ?? specifier;
  const segments = fromFile.split('/').slice(0, -1);
  for (const part of specifier.split('/')) {
    if (part === '..') segments.pop();
    else if (part !== '.') segments.push(part);
  }
  return segments.length > 1 ? (segments[0] ?? '') : '<root>';
}

// --- Effectful helpers ---

/** Every .ts file under `root`, as a path relative to it with forward slashes; [] when `root` is absent. */
export function listSources(root: string): string[] {
  const walk = (dir: string): string[] => {
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return [];
    }
    return entries.flatMap((name) => {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) return walk(full);
      return name.endsWith('.ts') ? [relative(root, full).split(sep).join('/')] : [];
    });
  };
  return walk(root);
}

/** The text of one source file. */
export function readSource(root: string, file: string): string {
  return readFileSync(join(root, file), 'utf8');
}
