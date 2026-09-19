// lib/review-settled.mjs -- the "review settled" decision, pure.
//
// A pull request's review is settled when, for every required reviewer,
// that reviewer's newest review was submitted against the PR's CURRENT
// head commit, and every review thread on the PR is resolved. Head-SHA
// freshness is what makes a push after the last review reopen the
// question; thread resolution is what makes every finding end in a
// recorded state (fixed, rebutted, deferred, acknowledged) before the
// bot may land. Decided on template-tools issue #597 (threads-resolved
// plus head-SHA freshness; the reviewer turn cap is the stop and the
// human is the backstop past it).
//
// This module holds no I/O: bin/review-settled fetches the facts from
// GitHub and posts the commit status; this decides. Copilot's reviews
// are submitted with state COMMENTED, never APPROVED, so a review's
// state is deliberately not part of the decision -- only its existence,
// its author and its commit.

/** Review states that count as "a review happened". */
const COUNTED_STATES = new Set(['APPROVED', 'CHANGES_REQUESTED', 'COMMENTED']);

/** GraphQL gives `copilot-pull-request-reviewer`; REST gives the same login
 * with a `[bot]` suffix. Compare on the bare login, case-insensitively. */
export function normalizeLogin(login) {
  return String(login ?? '').replace(/\[bot\]$/i, '').toLowerCase();
}

/** Parse the `reviewers` input: comma or whitespace separated logins. */
export function parseReviewers(text) {
  return [...new Set(
    String(text ?? '')
      .split(/[\s,]+/)
      .map(normalizeLogin)
      .filter((login) => login !== ''),
  )];
}

const short = (sha) => String(sha ?? '').slice(0, 7);

/**
 * Newest counted review by `reviewer`, or null. `reviews` are
 * `{ author, state, submittedAt, commit }` (author and commit as bare
 * strings), in any order.
 */
export function newestReviewBy(reviews, reviewer) {
  let newest = null;
  for (const review of reviews) {
    if (normalizeLogin(review.author) !== reviewer) continue;
    if (!COUNTED_STATES.has(review.state)) continue;
    if (newest === null || String(review.submittedAt) > String(newest.submittedAt)) {
      newest = review;
    }
  }
  return newest;
}

/**
 * The decision. Returns `{ state: 'success' | 'failure', description }`
 * where `description` fits GitHub's 140-character status limit and names
 * the FIRST reason the review is not settled (the reasons are checked in
 * the order a fix would address them: no review, stale review, open
 * threads).
 */
export function settle({ headSha, reviews, threads, reviewers }) {
  if (reviewers.length === 0) {
    return { state: 'failure', description: 'no required reviewer configured' };
  }
  for (const reviewer of reviewers) {
    const newest = newestReviewBy(reviews, reviewer);
    if (newest === null) {
      return { state: 'failure', description: clamp(`no review from ${reviewer} yet`) };
    }
    if (newest.commit !== headSha) {
      return {
        state: 'failure',
        description: clamp(
          `newest review by ${reviewer} is on ${short(newest.commit)}; head is ${short(headSha)} -- re-review needed`,
        ),
      };
    }
  }
  const open = threads.filter((thread) => !thread.isResolved).length;
  if (open > 0) {
    return {
      state: 'failure',
      description: clamp(`${open} unresolved review thread${open === 1 ? '' : 's'}`),
    };
  }
  return {
    state: 'success',
    description: clamp(`reviewed on head by ${reviewers.join(', ')}; all threads resolved`),
  };
}

const MAX_DESCRIPTION = 140;

export function clamp(text) {
  const s = String(text);
  return s.length <= MAX_DESCRIPTION ? s : `${s.slice(0, MAX_DESCRIPTION - 3)}...`;
}
