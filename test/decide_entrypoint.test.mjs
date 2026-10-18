// decide entrypoint tests: direct execution must still work through release
// symlinks, which is how the installed tds-utils command is reached.

import assert from 'node:assert/strict';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';

import { isInvokedDirectly } from '../bin/decide';

test('decide recognizes file and parent-directory symlink invocations', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'tds-decide-entrypoint-'));
  const realScript = resolve('bin/decide');
  const fileLink = join(root, 'decide');
  const directoryLink = join(root, 'release');

  try {
    const directoryType = process.platform === 'win32' ? 'junction' : 'dir';
    try {
      await symlink(realScript, fileLink, 'file');
      await symlink(dirname(realScript), directoryLink, directoryType);
    } catch (error) {
      if (error?.code === 'EPERM' || error?.code === 'EACCES') {
        t.skip(`symlinks unavailable in this environment: ${error.code}`);
        return;
      }
      throw error;
    }

    const moduleUrl = pathToFileURL(realScript).href;
    assert.equal(isInvokedDirectly(moduleUrl, fileLink), true);
    assert.equal(isInvokedDirectly(moduleUrl, join(directoryLink, 'decide')), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
