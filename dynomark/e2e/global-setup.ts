/// <reference types="node" />
// global-setup.ts -- before any scenario: build the extension (its dist/ is
// what Chromium loads unpacked) and sync the daemon's environment (its
// dynomark-host is what Chromium starts). Both packages must have their own
// dependencies installed first (`npm ci` in ../extension; uv is enough for
// the daemon); a missing one fails here, by name, not inside a scenario.

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { DAEMON_DIR, EXTENSION_DIR } from './support/paths.js';

export default function globalSetup(): void {
  if (!existsSync(`${EXTENSION_DIR}/node_modules`)) {
    throw new Error(`${EXTENSION_DIR}/node_modules is missing: run npm ci there first`);
  }
  execFileSync('npm', ['run', 'build'], { cwd: EXTENSION_DIR, stdio: 'inherit' });
  execFileSync('uv', ['sync', '--frozen'], { cwd: DAEMON_DIR, stdio: 'inherit' });
}
