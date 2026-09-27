// copy-static.mjs -- copy the MV3 manifest and static pages into dist/ after tsc.
//
// No bundler: MV3 loads ES modules natively, so tsc's output in dist/ is the
// extension, and this script only adds the files tsc does not emit.

import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const STATIC_ENTRIES = ['manifest.json', 'static'];

function copyEntry(name) {
  const from = join(ROOT, name);
  if (!existsSync(from)) return;
  cpSync(from, join(DIST, name), { recursive: true });
}

function main() {
  mkdirSync(DIST, { recursive: true });
  STATIC_ENTRIES.forEach(copyEntry);
}

main();
