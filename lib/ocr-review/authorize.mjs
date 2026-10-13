// lib/ocr-review/authorize.mjs -- OCR on Demand: who may start a review,
// and on which pull request (docs/design/OCR-ON-DEMAND.DESIGN.md, G2 and
// the Authorize job table).
//
// The authorize job references no secret; the review job `needs:` it and
// runs only on `approve`, so the job that loads credentials never starts
// for an unauthorized trigger. This module is that decision and nothing
// else: the rules are pure, and the one flow function takes the
// pull-request reader as a port (bin/ocr-review wires the GitHub adapter).
//
// Decisions:
//   skip     not an /ocr comment, or its author is not a collaborator.
//            No record, no comment (State Machine: SKIPPED).
//   fail     pr-not-open (missing, closed, or an issue that is not a PR)
//            or fork (head repo differs from base repo).
//   approve  the review job may run, with the PR's head and base.

// --- Constants --------------------------------------------------------------

/** GitHub's author associations that may start a review by comment. */
const AUTHORIZED_ASSOCIATIONS = new Set(['OWNER', 'MEMBER', 'COLLABORATOR']);

/** The command prefix; case-sensitive, at the very start of the body. */
const COMMAND = '/ocr';

// --- Predicates -------------------------------------------------------------

/** True when a comment body starts with the /ocr command. */
export function isOcrCommand(body) {
  return typeof body === 'string' && body.startsWith(COMMAND);
}

/** True for OWNER, MEMBER or COLLABORATOR. */
export function isAuthorizedAssociation(association) {
  return AUTHORIZED_ASSOCIATIONS.has(String(association ?? ''));
}

/** True for a usable pull-request number. */
function isPullNumber(pr) {
  return Number.isInteger(pr) && pr > 0;
}

const sameRepo = (a, b) => typeof a === 'string' && typeof b === 'string' && a.toLowerCase() === b.toLowerCase();

// --- Pure helpers -----------------------------------------------------------

/**
 * First gate, from the event alone: a comment must be an /ocr command from a
 * collaborator; a dispatch already needed write access (GitHub's rule).
 * Returns { decision: 'skip' | 'proceed', reason }.
 */
export function screenTrigger({ trigger, commentBody, association }) {
  if (trigger !== 'comment') return { decision: 'proceed', reason: 'dispatch' };
  if (!isOcrCommand(commentBody)) return { decision: 'skip', reason: 'comment is not an /ocr command' };
  if (!isAuthorizedAssociation(association)) {
    return { decision: 'skip', reason: `author association ${association || 'NONE'} may not start a review` };
  }
  return { decision: 'proceed', reason: 'authorized /ocr comment' };
}

/**
 * Second gate, from the pull request's facts (null when it does not exist,
 * which is also what an issue that is not a PR reads as).
 */
export function judgePullRequest(pr) {
  if (!pr || pr.state !== 'open') {
    return { decision: 'fail', cause: 'pr-not-open', reason: pr ? `pull request is ${pr.state}` : 'no such pull request' };
  }
  if (!sameRepo(pr.headRepo, pr.baseRepo)) {
    return { decision: 'fail', cause: 'fork', reason: 'head repository differs from the base repository' };
  }
  return { decision: 'approve', cause: null, reason: 'open same-repository pull request', headSha: pr.headSha, baseRef: pr.baseRef };
}

// --- Flow -------------------------------------------------------------------

/**
 * The authorize behavior. `event` is { trigger, commentBody, association, pr };
 * `pulls.readPullRequest(number)` resolves to the PR's facts or null.
 */
export async function authorizeRun(event, { readPullRequest }) {
  const screened = screenTrigger(event);
  if (screened.decision === 'skip') return { decision: 'skip', cause: null, reason: screened.reason };
  if (!isPullNumber(event.pr)) return { decision: 'fail', cause: 'pr-not-open', reason: `not a pull request number: ${event.pr}` };
  return judgePullRequest(await readPullRequest(event.pr));
}
