// test/ocr_review_git.test.mjs -- OCR on Demand: the verdict's git runner
// (bin/ocr-review gitIn). A git child that exits before reading its stdin
// must fail with git's own exit code and stderr, never crash the step with
// an unhandled EPIPE (tds-utils Issue#449: a successful review was recorded
// as `unexpected` and git's real error was lost).
// Real processes, a fake `git` on PATH; no network.
// Run: node --test test/ocr_review_git.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gitIn } from '../bin/ocr-review';

function withFakeGit(script, fn) {
  const dir = mkdtempSync(join(tmpdir(), 'ocr-git-'));
  const git = join(dir, 'git');
  writeFileSync(git, `#!/bin/sh\n${script}\n`);
  chmodSync(git, 0o755);
  const saved = process.env.PATH;
  process.env.PATH = `${dir}:${saved}`;
  return fn().finally(() => {
    process.env.PATH = saved;
    rmSync(dir, { recursive: true, force: true });
  });
}

test('a git that exits before reading its stdin fails with its own exit code and stderr, not an EPIPE crash', async () => {
  // 4 MiB of stdin overflows the pipe buffer, so the write hits the closed pipe.
  const stdin = 'x'.repeat(4 * 1024 * 1024);
  await withFakeGit('echo "fatal: refusing for a test" >&2; exit 128', async () => {
    await assert.rejects(gitIn('.')(['check-attr', '--stdin'], stdin), (error) => {
      assert.match(String(error.message), /exited 128/);
      assert.match(String(error.message), /fatal: refusing for a test/);
      return true;
    });
  });
});

test('a git that reads its stdin and succeeds returns its stdout', async () => {
  await withFakeGit('cat >/dev/null; printf ok', async () => {
    assert.equal(await gitIn('.')(['check-attr', '--stdin'], 'a\0b\0'), 'ok');
  });
});
