// postbuild.mjs -- turn tsc's dist/ into a loadable unpacked MV3 extension.
//
// No bundler (none is on the tech radar): MV3 loads ES modules natively, so
// tsc's output is the extension. What tsc does not do, this does:
//   1. copy manifest.json and every file under static/ (the pages) into dist/;
//   2. vendor zod: copy its ESM build (the .js files only; they import each
//      other by relative path) into dist/vendor/zod/;
//   3. rewrite every bare `zod` specifier in the emitted modules to the
//      relative path of dist/vendor/zod/index.js, because an extension page
//      or service worker cannot resolve a bare specifier (no import map in a
//      service worker);
//   4. refuse the build if any module under dist/ still imports a bare
//      specifier -- the extension would fail to load at runtime otherwise.

import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// --- Constants ---

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const STATIC = join(ROOT, 'static');
const ZOD = join(ROOT, 'node_modules', 'zod');
const VENDOR_ZOD = join(DIST, 'vendor', 'zod');

/** `from 'x'`, `import 'x'` and `import('x')`, capturing the quote and the specifier. */
const SPECIFIER = /(\bfrom\s*|\bimport\s*\(?\s*)(['"])([^'"]+)\2/g;
/** Whole-line `//` comments and block comments: prose there may quote an import. */
const COMMENTS = /^\s*\/\/.*$|\/\*[\s\S]*?\*\//gm;

// --- Predicates ---

function isBare(specifier) {
  return !specifier.startsWith('./') && !specifier.startsWith('../') && !specifier.startsWith('/');
}

// --- Pure helpers ---

/** The source with every bare `zod` import pointing at `zodPath` (a ./ or ../ path). */
function rewriteZod(source, zodPath) {
  return source.replace(SPECIFIER, (whole, lead, quote, spec) => (spec === 'zod' ? `${lead}${quote}${zodPath}${quote}` : whole));
}

/** Every bare specifier the module still imports (comments ignored). */
function bareSpecifiers(source) {
  return [...source.replace(COMMENTS, '').matchAll(SPECIFIER)].map((m) => m[3]).filter(isBare);
}

function toImportPath(fromDir, target) {
  const rel = relative(fromDir, target).split(sep).join('/');
  return rel.startsWith('.') ? rel : `./${rel}`;
}

// --- Effectful helpers ---

function walk(dir, keep) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full, keep);
    return keep(full) ? [full] : [];
  });
}

function copyStatic() {
  cpSync(join(ROOT, 'manifest.json'), join(DIST, 'manifest.json'));
  if (existsSync(STATIC)) cpSync(STATIC, DIST, { recursive: true });
}

function vendorZod() {
  for (const file of walk(ZOD, (f) => f.endsWith('.js') && !f.includes(`${sep}src${sep}`))) {
    const to = join(VENDOR_ZOD, relative(ZOD, file));
    mkdirSync(dirname(to), { recursive: true });
    cpSync(file, to);
  }
}

function rewriteModules() {
  const zodIndex = join(VENDOR_ZOD, 'index.js');
  for (const file of walk(DIST, (f) => f.endsWith('.js') && !f.startsWith(VENDOR_ZOD))) {
    const source = readFileSync(file, 'utf8');
    const rewritten = rewriteZod(source, toImportPath(dirname(file), zodIndex));
    if (rewritten !== source) writeFileSync(file, rewritten);
  }
}

function verifyNoBareSpecifiers() {
  const offenders = walk(DIST, (f) => f.endsWith('.js')).flatMap((file) =>
    bareSpecifiers(readFileSync(file, 'utf8')).map((spec) => `${relative(DIST, file)} -> ${spec}`),
  );
  if (offenders.length > 0) throw new Error(`bare import specifiers left in dist/ (not loadable in MV3):\n  ${offenders.join('\n  ')}`);
}

// --- Main ---

function main() {
  mkdirSync(DIST, { recursive: true });
  copyStatic();
  vendorZod();
  rewriteModules();
  verifyNoBareSpecifiers();
}

main();
