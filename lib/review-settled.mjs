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
//
// FAIL-OPEN on quota, deliberately (tds-internal#93), and ONLY on quota.
// When a required reviewer's newest post is its quota notice ("... unable
// to review this pull request because ... reached their quota limit"),
// on any commit, it is out of quota and will never review: the head does
// not wait for it, and the status reads "FAIL-OPEN: <reviewer> is out of
// quota", never "reviewed". Every review thread must still be resolved.
// Any OTHER failure notice ("encountered an error and was unable to
// review ...") is neither a review nor a go: the status stays red until
// the reviewer is re-requested and answers. Silence is not a go either.
// No notice of any kind is ever counted as a review.

/** A reviewer's "I could not review" reply, whatever the cause. */
const FAILURE_NOTICE = /unable to review this pull request/i;
/** The one cause that fails open: the requesting account is out of quota. */
const QUOTA_CAUSE = /reached (?:their|its|your) quota limit/i;

/** True for any "unable to review" notice; such a post is never a review. */
export function isFailureNotice(review) {
  return FAILURE_NOTICE.test(String(review?.body ?? ''));
}

/** True only for the out-of-quota notice, the one notice that fails open. */
export function isQuotaNotice(review) {
  return isFailureNotice(review) && QUOTA_CAUSE.test(String(review?.body ?? ''));
}

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
 * The decision. Returns `{ state: 'success' | 'failure', description,
 * pending }` where `description` fits GitHub's 140-character status limit
 * and names the FIRST reason the review is not settled (the reasons are
 * checked in the order a fix would address them: no review, stale review,
 * open threads). `pending` is true when the only thing missing is a
 * reviewer's answer on this head -- the one case where waiting can change
 * the verdict.
 */
export function settle({ headSha, reviews, threads, reviewers }) {
  if (reviewers.length === 0) {
    return { state: 'failure', description: 'no required reviewer configured', pending: false };
  }
  const outOfQuota = [];
  const realReviews = reviews.filter((review) => !isFailureNotice(review));
  for (const reviewer of reviewers) {
    const newestPost = newestReviewBy(reviews, reviewer);
    if (newestPost !== null && isQuotaNotice(newestPost)) {
      outOfQuota.push(reviewer);
      continue;
    }
    if (newestPost !== null && isFailureNotice(newestPost)) {
      return {
        state: 'failure',
        description: clamp(`${reviewer} could not review (not a quota notice) -- re-request the review`),
        pending: false,
      };
    }
    const newest = newestReviewBy(realReviews, reviewer);
    if (newest === null) {
      return { state: 'failure', description: clamp(`no review from ${reviewer} yet`), pending: true };
    }
    if (newest.commit !== headSha) {
      return {
        state: 'failure',
        description: clamp(
          `newest review by ${reviewer} is on ${short(newest.commit)}; head is ${short(headSha)} -- re-review needed`,
        ),
        pending: true,
      };
    }
  }
  const open = threads.filter((thread) => !thread.isResolved).length;
  if (open > 0) {
    return {
      state: 'failure',
      description: clamp(`${open} unresolved review thread${open === 1 ? '' : 's'}`),
      pending: false,
    };
  }
  if (outOfQuota.length > 0) {
    const verb = outOfQuota.length === 1 ? 'is' : 'are';
    return {
      state: 'success',
      description: clamp(`FAIL-OPEN: ${outOfQuota.join(', ')} ${verb} out of quota; all threads resolved`),
      pending: false,
    };
  }
  return {
    state: 'success',
    description: clamp(`reviewed on head by ${reviewers.join(', ')}; all threads resolved`),
    pending: false,
  };
}

const MAX_DESCRIPTION = 140;

export function clamp(text) {
  const s = String(text);
  return s.length <= MAX_DESCRIPTION ? s : `${s.slice(0, MAX_DESCRIPTION - 3)}...`;
}
