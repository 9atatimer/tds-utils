// lib/review-settled.mjs -- the "review settled" decision, pure.
//
// A pull request's review is settled when, for every required reviewer,
// that reviewer's newest review was submitted against the PR's CURRENT
// head commit, and every review thread on the PR is resolved. A required
// entry may be an any-of group "a|b": it is satisfied when ANY member's
// newest review is on the head (e.g. Codex standing in for Copilot while
// Copilot has no quota). Entries still combine all-of. Head-SHA
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
// When a required reviewer's newest post is its quota notice, on any
// commit, it is out of quota and will never review: the head does
// not wait for it, and the status reads "FAIL-OPEN: <reviewer> is out of
// quota", never "reviewed". Every review thread must still be resolved.
// Any OTHER failure notice ("encountered an error and was unable to
// review ...") is neither a review nor a go: the status stays red until
// the reviewer is re-requested and answers. Silence is not a go either.
// No notice of any kind is ever counted as a review. For an any-of group
// the rules apply per member: a review on the head by any member settles
// it, and it fails open only when EVERY member is out of quota -- one
// member's quota notice waits for the others.
//
// A reviewer's POSTS are its reviews and its issue comments on the PR,
// ordered by time (a review's submittedAt, a comment's createdAt): Copilot
// answers out of quota with a review ("... unable to review this pull
// request because ... reached their quota limit"), Codex with an issue
// comment ("You have reached your Codex usage limits for code reviews
// ..."). Only a review can settle the head -- a comment carries no commit
// -- and a comment that is not a notice is neither a review nor a go.
//
// A reaction is never a review. Codex signals a clean pass with a
// thumbs-up and no review; a reaction carries no commit oid, and tying it
// to the head by time would trust commit timestamps, which the author
// controls -- that would fail open. So a clean Codex pass leaves the
// group red (fail closed) until some member posts a review on the head.

/** A reviewer's "I could not review" reply, whatever the cause. */
const FAILURE_NOTICE = /unable to review this pull request/i;
/** The one cause that fails open: the requesting account is out of quota. */
const QUOTA_CAUSE = /reached (?:their|its|your) quota limit/i;
/** Codex's own quota notice: an issue comment that OPENS with this
 * sentence. Anchored at the start so a review quoting it in passing is
 * not a notice. */
const CODEX_QUOTA = /^\s*You have reached your Codex usage limits for code reviews\b/i;

const bodyOf = (post) => String(post?.body ?? '');

/** True for any "could not review" notice; such a post is never a review. */
export function isFailureNotice(post) {
  return FAILURE_NOTICE.test(bodyOf(post)) || CODEX_QUOTA.test(bodyOf(post));
}

/** True only for an out-of-quota notice, the one notice that fails open. */
export function isQuotaNotice(post) {
  const body = bodyOf(post);
  return (FAILURE_NOTICE.test(body) && QUOTA_CAUSE.test(body)) || CODEX_QUOTA.test(body);
}

/** Review states that count as "a review happened". */
const COUNTED_STATES = new Set(['APPROVED', 'CHANGES_REQUESTED', 'COMMENTED']);

/** GraphQL gives `copilot-pull-request-reviewer`; REST gives the same login
 * with a `[bot]` suffix. Compare on the bare login, case-insensitively. */
export function normalizeLogin(login) {
  return String(login ?? '').replace(/\[bot\]$/i, '').toLowerCase();
}

/** Parse the `reviewers` input: comma or whitespace separated entries;
 * an entry "a|b" is one any-of group, returned normalized as "a|b". */
export function parseReviewers(text) {
  return [...new Set(
    String(text ?? '')
      .split(/[\s,]+/)
      .map((entry) => [...new Set(entry.split('|').map(normalizeLogin).filter((login) => login !== ''))].join('|'))
      .filter((entry) => entry !== ''),
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
 * Newest post by `reviewer` across counted reviews and issue comments, or
 * null. `comments` are `{ author, createdAt, body }`; a comment is placed
 * in time by `createdAt`, a review by `submittedAt`.
 */
export function newestPostBy(reviews, comments, reviewer) {
  let newest = newestReviewBy(reviews, reviewer);
  let at = newest === null ? '' : String(newest.submittedAt);
  for (const comment of comments) {
    if (normalizeLogin(comment.author) !== reviewer) continue;
    if (newest === null || String(comment.createdAt) > at) {
      newest = comment;
      at = String(comment.createdAt);
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
export function settle({ headSha, reviews, comments = [], threads, reviewers }) {
  if (reviewers.length === 0) {
    return { state: 'failure', description: 'no required reviewer configured', pending: false };
  }
  const outOfQuota = [];
  const realReviews = reviews.filter((review) => !isFailureNotice(review));
  for (const entry of reviewers) {
    // Classify each member by the single-reviewer rules; a group ("a|b")
    // passes when ANY member reviewed the head, fails open only when EVERY
    // member is out of quota, and otherwise reports the most actionable
    // reason. A one-member entry is exactly the single-reviewer rule.
    const members = entry.split('|');
    const status = members.map((member) => {
      const newestPost = newestPostBy(reviews, comments, member);
      if (newestPost !== null && isQuotaNotice(newestPost)) return { member, kind: 'quota' };
      if (newestPost !== null && isFailureNotice(newestPost)) return { member, kind: 'failed' };
      const newest = newestReviewBy(realReviews, member);
      if (newest === null) return { member, kind: 'none' };
      return { member, kind: newest.commit === headSha ? 'head' : 'stale', newest };
    });
    if (status.some((s) => s.kind === 'head')) continue;
    if (status.every((s) => s.kind === 'quota')) {
      outOfQuota.push(...members);
      continue;
    }
    const stale = status.filter((s) => s.kind === 'stale');
    if (stale.length > 0) {
      const latest = stale.reduce((x, y) => (String(y.newest.submittedAt) > String(x.newest.submittedAt) ? y : x));
      return {
        state: 'failure',
        description: clamp(
          `newest review by ${latest.member} is on ${short(latest.newest.commit)}; head is ${short(headSha)} -- re-review needed`,
        ),
        pending: true,
      };
    }
    const failed = status.find((s) => s.kind === 'failed');
    if (failed !== undefined && !status.some((s) => s.kind === 'none')) {
      return {
        state: 'failure',
        description: clamp(`${failed.member} could not review (not a quota notice) -- re-request the review`),
        pending: false,
      };
    }
    const waiting = status.filter((s) => s.kind === 'none').map((s) => s.member);
    return { state: 'failure', description: clamp(`no review from ${waiting.join(' or ')} yet`), pending: true };
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
