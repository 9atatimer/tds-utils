// test/review_settled_io.test.mjs -- the review-settled I/O layer (bin/),
// against a fake fetch. No network: every test installs its own stub.
// Run: node --test test/review_settled_io.test.mjs
//
// The decision itself is covered by review_settled.test.mjs; this file
// covers what that one cannot reach -- GraphQL paging, the fork-PR skip,
// and the status write -- because those are the parts that only ran in
// production before.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decide, postStatus, readPullRequest } from '../bin/review-settled';

const HEAD = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

/** Install a fake fetch for one test; returns the recorded calls. */
function stubFetch(handler) {
  const calls = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init, body: init?.body ? JSON.parse(init.body) : undefined });
    return handler(calls.length, calls.at(-1));
  };
  return {
    calls,
    restore: () => {
      globalThis.fetch = real;
    },
  };
}

const ok = (data) => ({ ok: true, status: 200, json: async () => ({ data }), text: async () => '' });

const prPage = (over) => ({
  repository: {
    pullRequest: {
      headRefOid: HEAD,
      isCrossRepository: false,
      reviews: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [] },
      reviewThreads: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [] },
      ...over,
    },
  },
});

test('reviews are paged, not capped at one response', async () => {
  const review = (commit) => ({
    author: { login: 'copilot-pull-request-reviewer' },
    state: 'COMMENTED',
    submittedAt: '2026-09-18T20:00:00Z',
    commit: { oid: commit },
  });
  const stub = stubFetch((n) =>
    ok(
      prPage(
        n === 1
          ? { reviews: { pageInfo: { hasNextPage: true, endCursor: 'r1' }, nodes: [review('old')] } }
          : { reviews: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [review(HEAD)] } },
      ),
    ),
  );
  try {
    const facts = await readPullRequest('t', 'o', 'n', 1);
    assert.equal(facts.reviews.length, 2, 'both pages of reviews are collected');
    assert.ok(
      facts.reviews.some((r) => r.commit === HEAD),
      'the review on head, which is on the second page, is not lost',
    );
    assert.equal(stub.calls.length, 2);
    assert.equal(stub.calls[1].body.variables.reviewsAfter, 'r1', 'the reviews cursor is passed on');
  } finally {
    stub.restore();
  }
});

test('review threads are paged independently of reviews', async () => {
  const stub = stubFetch((n) =>
    ok(
      prPage(
        n === 1
          ? { reviewThreads: { pageInfo: { hasNextPage: true, endCursor: 't1' }, nodes: [{ isResolved: true }] } }
          : { reviewThreads: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [{ isResolved: false }] } },
      ),
    ),
  );
  try {
    const facts = await readPullRequest('t', 'o', 'n', 1);
    assert.equal(facts.threads.length, 2);
    assert.ok(
      facts.threads.some((t) => t.isResolved === false),
      'the unresolved thread on the second page is seen',
    );
  } finally {
    stub.restore();
  }
});

test('a fork PR is reported as cross-repository so no status is posted', async () => {
  const stub = stubFetch(() => ok(prPage({ isCrossRepository: true })));
  try {
    const facts = await readPullRequest('t', 'o', 'n', 1);
    assert.equal(facts.isCrossRepository, true);
  } finally {
    stub.restore();
  }
});

test('a missing pull request is an error, not an empty verdict', async () => {
  const stub = stubFetch(() => ok({ repository: { pullRequest: null } }));
  try {
    await assert.rejects(() => readPullRequest('t', 'o', 'n', 7), /no pull request o\/n#7/);
  } finally {
    stub.restore();
  }
});

test('a GraphQL error body is surfaced, never treated as no reviews', async () => {
  const stub = stubFetch(() => ({
    ok: true,
    status: 200,
    json: async () => ({ errors: [{ message: 'rate limited' }] }),
    text: async () => '',
  }));
  try {
    await assert.rejects(() => readPullRequest('t', 'o', 'n', 1), /rate limited/);
  } finally {
    stub.restore();
  }
});

test('postStatus sends the verdict to the head sha under the review-settled context', async () => {
  const stub = stubFetch(() => ({ ok: true, status: 201, json: async () => ({}), text: async () => '' }));
  try {
    await postStatus('t', 'o', 'n', HEAD, { state: 'success', description: 'all settled' });
    assert.equal(stub.calls.length, 1);
    assert.match(stub.calls[0].url, new RegExp(`/repos/o/n/statuses/${HEAD}$`));
    assert.equal(stub.calls[0].body.context, 'review-settled');
    assert.equal(stub.calls[0].body.state, 'success');
  } finally {
    stub.restore();
  }
});

test('a failed status write is an error, so the run goes red instead of lying', async () => {
  const stub = stubFetch(() => ({ ok: false, status: 403, json: async () => ({}), text: async () => 'forbidden' }));
  try {
    await assert.rejects(
      () => postStatus('t', 'o', 'n', HEAD, { state: 'success', description: 'x' }),
      /status POST HTTP 403/,
    );
  } finally {
    stub.restore();
  }
});

test('review bodies are read, so a quota notice can be told from a review', async () => {
  const stub = stubFetch(() =>
    ok(
      prPage({
        reviews: {
          pageInfo: { hasNextPage: false, endCursor: null },
          nodes: [
            {
              author: { login: 'copilot-pull-request-reviewer' },
              state: 'COMMENTED',
              submittedAt: '2026-09-18T20:00:00Z',
              commit: { oid: HEAD },
              body: 'quota text',
            },
          ],
        },
      }),
    ),
  );
  try {
    const facts = await readPullRequest('t', 'o', 'n', 1);
    assert.equal(facts.reviews[0].body, 'quota text');
    assert.match(stub.calls[0].body.query, /\bbody\b/, 'the query asks for review bodies');
  } finally {
    stub.restore();
  }
});

// GitHub runs no workflow on Copilot's reviews, so the checker waits a
// bounded time for the reviewer's answer before it posts.
const COPILOT_NODE = (commit, body) => ({
  author: { login: 'copilot-pull-request-reviewer' },
  state: 'COMMENTED',
  submittedAt: '2026-09-18T20:00:00Z',
  commit: { oid: commit },
  body,
});

function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; } };
}

test('decide waits while the reviewer has not answered, and posts its answer', async () => {
  const quota =
    'Copilot was unable to review this pull request because the user who requested the review has reached their quota limit.';
  const stub = stubFetch((n) =>
    ok(
      prPage({
        reviews: {
          pageInfo: { hasNextPage: false, endCursor: null },
          nodes: n < 3 ? [] : [COPILOT_NODE(HEAD, quota)],
        },
      }),
    ),
  );
  const c = clock();
  try {
    const { verdict } = await decide('t', 'o', 'n', 1, ['copilot-pull-request-reviewer'], 180, c);
    assert.equal(verdict.state, 'success');
    assert.match(verdict.description, /^FAIL-OPEN/);
    assert.equal(stub.calls.length, 3, 'read, waited, re-read until the notice arrived');
  } finally {
    stub.restore();
  }
});

test('decide gives up at the deadline and posts red', async () => {
  const stub = stubFetch(() => ok(prPage({})));
  const c = clock();
  try {
    const { verdict } = await decide('t', 'o', 'n', 1, ['copilot-pull-request-reviewer'], 60, c);
    assert.equal(verdict.state, 'failure');
    assert.ok(c.now() <= 60_000 + 15_000, 'never waits past the deadline by more than one poll');
  } finally {
    stub.restore();
  }
});

test('decide does not wait on an answer that waiting cannot change', async () => {
  const stub = stubFetch(() =>
    ok(
      prPage({
        reviews: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [COPILOT_NODE(HEAD, 'Reviewed.')] },
        reviewThreads: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [{ isResolved: false }] },
      }),
    ),
  );
  const c = clock();
  try {
    await decide('t', 'o', 'n', 1, ['copilot-pull-request-reviewer'], 180, c);
    assert.equal(stub.calls.length, 1, 'an open thread is a human matter: no polling');
    assert.equal(c.now(), 0);
  } finally {
    stub.restore();
  }
});

test('decide with no wait reads once', async () => {
  const stub = stubFetch(() => ok(prPage({})));
  try {
    await decide('t', 'o', 'n', 1, ['copilot-pull-request-reviewer'], 0, clock());
    assert.equal(stub.calls.length, 1);
  } finally {
    stub.restore();
  }
});
