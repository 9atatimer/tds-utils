// postbuild.mjs -- turn tsc's dist/ into a loadable unpacked MV3 extension
// for Chrome, and write its Firefox twin to dist-firefox/ (task-032).
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
//      specifier -- the extension would fail to load at runtime otherwise;
//   5. copy dist/ to dist-firefox/ and write there the Firefox manifest,
//      derived from manifest.json so the two never ask for different
//      permissions: background scripts (Firefox runs an event page, not a
//      service worker) on the Firefox entry, the pinned gecko id the
//      daemon's host manifest allows, options_ui for options_page, the
//      sidebar as the chat surface with the chat shortcut opening it, and no
//      Chrome `key`.

import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// --- Constants ---

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const STATIC = join(ROOT, 'static');
const ZOD = join(ROOT, 'node_modules', 'zod');
const VENDOR_ZOD = join(DIST, 'vendor', 'zod');
const DIST_FIREFOX = join(ROOT, 'dist-firefox');

/** The Firefox add-on id; `dynomark-daemon install-host-manifest --browser firefox` allows exactly it. */
const GECKO_ID = 'dynomark@tds.dynomark';
/** The oldest Firefox with everything used: MV3 module background scripts, scripting.executeScript with func, sidebar_action (ESR 128). */
const FIREFOX_MIN_VERSION = '128.0';
const FIREFOX_BACKGROUND = 'firefoxBackground.js';
const CHAT_PAGE = 'chat.html';
const OPEN_CHAT_COMMAND = 'open-chat';

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

/** The Firefox manifest for the Chrome one: same permissions, keyword, popup and pages; Firefox's own background, id, options and sidebar. */
function firefoxManifest(chrome) {
  const { key: _key, background: _background, options_page: optionsPage, commands, ...shared } = chrome;
  const openChat = commands?.[OPEN_CHAT_COMMAND];
  if (openChat === undefined) throw new Error(`manifest.json has no ${OPEN_CHAT_COMMAND} command for the Firefox sidebar shortcut`);
  return {
    ...shared,
    background: { scripts: [FIREFOX_BACKGROUND], type: 'module' },
    options_ui: { page: optionsPage, open_in_tab: true },
    sidebar_action: { default_title: shared.name, default_panel: CHAT_PAGE, open_at_install: false },
    commands: { _execute_sidebar_action: { suggested_key: openChat.suggested_key, description: openChat.description } },
    browser_specific_settings: { gecko: { id: GECKO_ID, strict_min_version: FIREFOX_MIN_VERSION } },
  };
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

function writeFirefox() {
  const chrome = JSON.parse(readFileSync(join(ROOT, 'manifest.json'), 'utf8'));
  const manifest = firefoxManifest(chrome);
  rmSync(DIST_FIREFOX, { recursive: true, force: true });
  cpSync(DIST, DIST_FIREFOX, { recursive: true });
  writeFileSync(join(DIST_FIREFOX, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
}

// --- Main ---

function main() {
  mkdirSync(DIST, { recursive: true });
  copyStatic();
  vendorZod();
  rewriteModules();
  verifyNoBareSpecifiers();
  writeFirefox();
}

main();
