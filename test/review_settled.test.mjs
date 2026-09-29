// test/review_settled.test.mjs -- the review-settled decision (lib/), pure.
// Run: node --test test/review_settled.test.mjs (or test/smoketest_review_settled.sh).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  clamp,
  isFailureNotice,
  isQuotaNotice,
  newestReviewBy,
  normalizeLogin,
  parseReviewers,
  settle,
} from '../lib/review-settled.mjs';

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

// --- any-of groups: "a|b" is satisfied by a review on head from either ---

const CODEX = 'chatgpt-codex-connector';
const EITHER = `${COPILOT}|${CODEX}`;

test('parseReviewers keeps an a|b group as one normalized entry', () => {
  assert.deepEqual(parseReviewers('Copilot-Pull-Request-Reviewer[bot]|chatgpt-codex-connector[bot], other'),
    [EITHER, 'other']);
  assert.deepEqual(parseReviewers(`${COPILOT}|${COPILOT}`), [COPILOT]);
});

test('any-of group: a review on head from the second member settles it', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ author: `${CODEX}[bot]` })], threads: [], reviewers: [EITHER] });
  assert.equal(v.state, 'success');
});

test('any-of group: no review from any member -> failure naming every member', () => {
  const v = settle({ headSha: HEAD, reviews: [], threads: [], reviewers: [EITHER] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from copilot-pull-request-reviewer or chatgpt-codex-connector yet/);
});

test('any-of group: only stale reviews -> failure naming the newest stale reviewer', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [
      review({ commit: OLD, submittedAt: '2026-09-18T20:00:00Z' }),
      review({ author: CODEX, commit: OLD, submittedAt: '2026-09-19T20:00:00Z' }),
    ],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /newest review by chatgpt-codex-connector is on bbbbbbb; head is aaaaaaa/);
});

test('any-of group: one member on head settles it even if the other is stale', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ commit: OLD }), review({ author: CODEX })],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'success');
});

test('any-of group still composes with all-of: a|b, c needs c too', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ author: CODEX })], threads: [], reviewers: [EITHER, 'human'] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from human yet/);
});

test('any-of group: open threads still block', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ author: CODEX })], threads: [{ isResolved: false }], reviewers: [EITHER] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /1 unresolved review thread/);
});

// --- Fail-open on quota, and only on quota (tds-internal#93). Copilot
// out of quota will never review, so its quota notice is a go: the head
// does not wait for it. Any other Copilot failure notice is not a review
// and not a go. Silence is not a go either.

const QUOTA =
  'Copilot was unable to review this pull request because the user who requested the review has reached their quota limit.';
const ERROR =
  'Copilot encountered an error and was unable to review this pull request. You can try again by re-requesting a review.';

test('isQuotaNotice matches the quota notice and nothing else', () => {
  assert.equal(isQuotaNotice(review({ body: QUOTA })), true);
  assert.equal(isQuotaNotice(review({ body: ERROR })), false);
  assert.equal(isQuotaNotice(review({ body: 'Looks good; one nit below.' })), false);
  assert.equal(isQuotaNotice(review({})), false);
});

test('isFailureNotice matches any unable-to-review notice', () => {
  assert.equal(isFailureNotice(review({ body: QUOTA })), true);
  assert.equal(isFailureNotice(review({ body: ERROR })), true);
  assert.equal(isFailureNotice(review({ body: 'Reviewed.' })), false);
});

test('a quota notice on head fails open, and says so', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ body: QUOTA })], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'success');
  assert.equal(v.description, 'FAIL-OPEN: copilot-pull-request-reviewer is out of quota; all threads resolved');
  assert.equal(v.pending, false);
});

test('a quota notice on an older commit still fails open: nothing since says otherwise', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ body: QUOTA, commit: OLD })], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'success');
  assert.match(v.description, /^FAIL-OPEN/);
});

test('a quota notice never reads as a review', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ body: QUOTA })], threads: [], reviewers: [COPILOT] });
  assert.doesNotMatch(v.description, /reviewed on head/);
});

test('any other failure notice is not a go, and not a review', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ body: ERROR })], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /copilot-pull-request-reviewer could not review/);
  assert.doesNotMatch(v.description, /reviewed on head|FAIL-OPEN/);
  assert.equal(v.pending, false, 'an error notice is an answer: waiting will not change it');
});

test('an error notice after a real review on head still blocks: the newest post decides', () => {
  const reviews = [
    review({ body: 'Reviewed.', submittedAt: '2026-09-18T19:00:00Z' }),
    review({ body: ERROR, submittedAt: '2026-09-18T20:00:00Z' }),
  ];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
});

test('a real review after a quota notice is judged as a review again', () => {
  const reviews = [
    review({ body: QUOTA, submittedAt: '2026-09-18T19:00:00Z', commit: OLD }),
    review({ body: 'Reviewed.', submittedAt: '2026-09-18T20:00:00Z', commit: OLD }),
  ];
  const v = settle({ headSha: HEAD, reviews, threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /re-review needed/);
});

test('silence is not a go: no post at all stays red and pending', () => {
  const v = settle({ headSha: HEAD, reviews: [], threads: [], reviewers: [COPILOT] });
  assert.equal(v.state, 'failure');
  assert.equal(v.pending, true);
});

test('a stale review is pending; open threads are not', () => {
  assert.equal(
    settle({ headSha: HEAD, reviews: [review({ commit: OLD })], threads: [], reviewers: [COPILOT] }).pending,
    true,
  );
  assert.equal(
    settle({ headSha: HEAD, reviews: [review()], threads: [{ isResolved: false }], reviewers: [COPILOT] }).pending,
    false,
  );
});

test('fail-open never waives an unresolved thread', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA })],
    threads: [{ isResolved: false }],
    reviewers: [COPILOT],
  });
  assert.equal(v.state, 'failure');
  assert.equal(v.description, '1 unresolved review thread');
});

test('one reviewer out of quota does not excuse another', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA })],
    threads: [],
    reviewers: [COPILOT, 'chatgpt-codex-connector'],
  });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /no review from chatgpt-codex-connector/);
});

// --- any-of groups meet fail-open: the rules apply per member ---

test('any-of group: Copilot out of quota and Codex reviewed on head -> reviewed, not fail-open', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA }), review({ author: CODEX })],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'success');
  assert.doesNotMatch(v.description, /FAIL-OPEN/);
});

test('any-of group: one member out of quota waits for the other', () => {
  const v = settle({ headSha: HEAD, reviews: [review({ body: QUOTA })], threads: [], reviewers: [EITHER] });
  assert.equal(v.state, 'failure');
  assert.equal(v.pending, true);
  assert.match(v.description, /no review from chatgpt-codex-connector yet/);
});

test('any-of group: every member out of quota -> fail-open naming both', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA }), review({ author: CODEX, body: QUOTA })],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'success');
  assert.match(v.description, /^FAIL-OPEN: copilot-pull-request-reviewer, chatgpt-codex-connector are out of quota/);
});

test('any-of group: a member error notice with the other out of quota stays red', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA }), review({ author: CODEX, body: ERROR })],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'failure');
  assert.equal(v.pending, false);
  assert.match(v.description, /chatgpt-codex-connector could not review/);
});

test('any-of group: a stale real review is reported before a quota notice', () => {
  const v = settle({
    headSha: HEAD,
    reviews: [review({ body: QUOTA }), review({ author: CODEX, commit: OLD })],
    threads: [],
    reviewers: [EITHER],
  });
  assert.equal(v.state, 'failure');
  assert.match(v.description, /newest review by chatgpt-codex-connector is on bbbbbbb/);
});
