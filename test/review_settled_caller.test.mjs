// test/review_settled_caller.test.mjs -- the review-settled caller's wait
// policy, read as text. Copilot's answer fires no workflow, so the one run
// that waits for it is the run its review request starts; every other event
// fails fast. No network.
// Run: node --test test/review_settled_caller.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CALLER = readFileSync(join(ROOT, '.github/workflows/review-settled-caller.yml'), 'utf8')
  .split('\n')
  .filter((line) => !/^\s*#/.test(line))
  .join('\n');

test('a review request re-evaluates the head, so it can start the one waiting run', () => {
  const types = CALLER.match(/^ {2}pull_request:\n\s+types: \[([^\]]*)\]/m);
  assert.ok(types, 'pull_request trigger lists its types');
  assert.match(types[1], /\breview_requested\b/);
});

test('only a review_requested run waits for the reviewer; every other event posts at once', () => {
  const wait = CALLER.match(/^\s+wait_seconds: (.+)$/m);
  assert.ok(wait, 'the caller passes wait_seconds explicitly');
  assert.equal(
    wait[1].trim(),
    "${{ github.event.action == 'review_requested' && 180 || 0 }}",
  );
});

test('only a push or a review request cancels a waiting run; every other event queues behind it', () => {
  const cancel = CALLER.match(/^\s+cancel-in-progress: (.+)$/m);
  assert.ok(cancel, 'the concurrency group sets cancel-in-progress explicitly');
  assert.equal(
    cancel[1].trim(),
    "${{ github.event.action == 'synchronize' || github.event.action == 'review_requested' }}",
  );
});
