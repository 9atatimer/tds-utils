/// <reference types="node" />
// paths.ts -- where the two packages under test live, relative to this one.

import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

export const DYNOMARK_DIR = join(HERE, '..', '..');
export const EXTENSION_DIR = join(DYNOMARK_DIR, 'extension');
/** The unpacked extension `npm run build` writes. */
export const EXTENSION_DIST = join(EXTENSION_DIR, 'dist');
export const DAEMON_DIR = join(DYNOMARK_DIR, 'daemon');
/** The daemon's console scripts, installed by `uv sync`. */
export const DAEMON_BIN = join(DAEMON_DIR, '.venv', 'bin');
