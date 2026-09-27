/// <reference types="node" />
// layers.test.ts -- mechanical architecture tests (coding skill, section 1.2).
//
// Grep: no browser extension API outside src/adapters/ (design, "Core (stable,
// in the problem's language) ... None of these know a browser API").
// Arrow + Purity: every import crosses inward; src/domain imports only itself.

import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { importSpecifiers, importTarget, listSources, readSource, referencesBrowserApi } from './scan.js';

// --- Constants ---

const SRC = fileURLToPath(new URL('../../src', import.meta.url));

/** What each layer (first directory under src/) may import. `<root>` files are composition roots and may import anything. */
const ALLOWED_IMPORTS: Readonly<Record<string, readonly string[]>> = {
  domain: ['domain'],
  wire: ['domain', 'wire', 'zod'],
  ports: ['domain', 'ports', 'wire'],
  app: ['domain', 'ports', 'wire', 'app'],
  adapters: ['domain', 'ports', 'wire', 'adapters', 'zod'],
};

// --- Helpers ---

function layerOf(file: string): string {
  return file.includes('/') ? (file.split('/')[0] ?? '') : '<root>';
}

function forbiddenImports(file: string): string[] {
  const allowed = ALLOWED_IMPORTS[layerOf(file)];
  if (allowed === undefined) return layerOf(file) === '<root>' ? [] : [`unknown layer ${layerOf(file)}`];
  return importSpecifiers(readSource(SRC, file)).filter((spec) => !allowed.includes(importTarget(file, spec)));
}

// --- The guard itself (accept and refuse cases, so a broken scanner cannot pass vacuously) ---

describe('the architecture scanner', () => {
  it('Given a browser API call, a bracket access or the chrome types directive, When scanned, Then each is flagged', () => {
    expect(referencesBrowserApi('await chrome.bookmarks.getTree();')).toBe(true);
    expect(referencesBrowserApi("const b = browser?.['bookmarks'];")).toBe(true);
    expect(referencesBrowserApi('const t = globalThis.chrome.tabs;')).toBe(true);
    expect(referencesBrowserApi('/// <reference types="chrome" />\nexport {};')).toBe(true);
  });

  it('Given a browser API named only in a comment or as a plain word, When scanned, Then nothing is flagged', () => {
    expect(referencesBrowserApi('// the adapter wraps chrome.bookmarks\nconst u = "https://x/"; /* browser.tabs */')).toBe(false);
    expect(referencesBrowserApi('const chromeless = 1; const browserName = "x";')).toBe(false);
  });

  it('Given relative and package imports, When resolved, Then each names its target layer or package', () => {
    const source =
      "import type { A } from '../domain/tree.js';\nexport { B } from './x.js';\nimport 'zod';\nconst c = import('../adapters/y.js');";
    const targets = importSpecifiers(source).map((spec) => importTarget('app/use.ts', spec));
    expect(targets.sort()).toEqual(['adapters', 'app', 'domain', 'zod']);
  });
});

// --- The rules over src/ ---

describe('extension source layering', () => {
  it('Given any file outside src/adapters/, When scanned, Then it never references chrome.* or browser.*', () => {
    const offenders = listSources(SRC).filter((f) => !f.startsWith('adapters/') && referencesBrowserApi(readSource(SRC, f)));
    expect(offenders).toEqual([]);
  });

  it('Given any layer, When its imports are resolved, Then each points inward (src/domain imports only src/domain)', () => {
    const offenders = listSources(SRC).flatMap((f) => forbiddenImports(f).map((spec) => `${f} -> ${spec}`));
    expect(offenders).toEqual([]);
  });
});
