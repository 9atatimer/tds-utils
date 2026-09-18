// test/review_settled.test.mjs -- the review-settled decision (lib/), pure.
// Run: node --test test/review_settled.test.mjs (or test/smoketest_review_settled.sh).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clamp, newestReviewBy, normalizeLogin, parseReviewers, settle } from '../lib/review-settled.mjs';

const HEAD = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const OLD = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const COPILOT = 'copilot-pull-request-reviewer';

const review = (over) => ({
  author: COPILOT,
  state: 'COMMENTED',
  submittedAt: '2026-09-18T20:00:00Z',
  commit: HEAD,
  ...over,
});

test('normalizeLogin strips the [bot] suffix and case', () => {
  assert.equal(normalizeLogin('Copilot-Pull-Request-Reviewer[bot]'), COPILOT);
  assert.equal(normalizeLogin(COPILOT), COPILOT);
  assert.equal(normalizeLogin(undefined), '');
});

test('parseReviewers splits on commas and whitespace, dedupes, normalizes', () => {
  assert.deepEqual(parseReviewers('copilot-pull-request-reviewer[bot], chatgpt-codex-connector  COPILOT-pull-request-reviewer'),
    [COPILOT, 'chatgpt-codex-connector']);
  assert.deepEqual(parseReviewers(''), []);
});

test('no review from the required reviewer -> failure naming them', () => {
  const v = settle({ headSha: HEAD, reviews: [], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from copilot-pull-request-reviewer yet/);
});

test('a review by someone else does not count', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ author: 'human' })], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from/);
});

test('newest review on an older commit -> failure naming both shas', () => {
  const reviews = [
    review({ commit: HEAD, submittedAt: '2026-09-18T19:00:00Z' }),
    review({ commit: OLD, submittedAt: '2026-09-18T20:00:00Z' }),
  ];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /on bbbbbbb; head is aaaaaaa/);
});

test('an older review on an older commit is superseded by a newer one on head', () => {
  const reviews = [
    review({ commit: OLD, submittedAt: '2026-09-18T19:00:00Z' }),
    review({ commit: HEAD, submittedAt: '2026-09-18T20:00:00Z' }),
  ];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'success');
});

test('dismissed and pending reviews are not reviews', () => {
  const reviews = [
    review({ commit: HEAD, state: 'DISMISSED' }),
    review({ commit: HEAD, state: 'PENDING', submittedAt: '2026-09-18T21:00:00Z' }),
  ];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from/);
});

test('an unresolved thread -> failure with the count', () => {
  const threads = [{ isResolved: true }, { isResolved: false }, { isResolved: false }];
  const v = settle({ headSha: HEAD, reviews: [review()], threads, reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.equal(v.description, '2 unresolved review threads');
});

test('one unresolved thread is singular', () => {
  const v = settle({ headSha: HEAD, reviews: [review()], threads: [{ isResolved: false }], reviewers: [COPILOT] });
  assert.equal(v.description, '1 unresolved review thread');
});

test('reviewed on head with every thread resolved -> success', () => {
  const threads = [{ isResolved: true }];
  const v = settle({ headSha: HEAD, reviews: [review()], threads, reviewers: [COPILOT] });
  assert.equal(v.state, 'success');
  assert.match(v.description, /reviewed on head by copilot-pull-request-reviewer; all threads resolved/);
});

test('stale review is reported before open threads', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ commit: OLD })], threads: [{ isResolved: false }], reviewers: [COPILOT] });
  assert.match(v.description, /re-review needed/);
});

test('every required reviewer must be on head', () => {
  const reviews = [review(), review({ author: 'chatgpt-codex-connector', commit: OLD })];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT, 'chatgpt-codex-connector'] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /chatgpt-codex-connector is on bbbbbbb/);
});

test('REST-style [bot] author matches a bare configured login', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ author: `${COPILOT}[bot]` })], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'success');
});

test('no reviewers configured is a failure, never a vacuous pass', () => {
  const v = settle({ headSha: HEAD, reviews: [review()], threads: [], reviewers: [] });
  assert.equal(v.state, 'failure');
});

test('newestReviewBy picks by submittedAt, not order', () => {
  const a = review({ submittedAt: '2026-09-18T20:00:00Z', commit: OLD });
  const b = review({ submittedAt: '2026-09-18T19:00:00Z', commit: HEAD });
  assert.equal(newestReviewBy([b, a], COPILOT), a);
  assert.equal(newestReviewBy([], COPILOT), null);
});

test('clamp keeps descriptions within GitHub\'s 140 characters', () => {
  assert.equal(clamp('x'.repeat(140)).length, 140);
  assert.equal(clamp('x'.repeat(141)).length, 140);
  assert.ok(clamp('x'.repeat(200)).endsWith('...'));
});
