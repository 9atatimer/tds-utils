// lib/ocr-review/reaction.mjs -- OCR on Demand: the reactions this workflow
// leaves on the /ocr comment that summoned it (docs/design/
// OCR-ON-DEMAND.DESIGN.md: Key Decisions, comment reactions row; owner
// request 2026-10-13).
//
// The authorize job acknowledges an approved /ocr comment with `eyes`; the
// report job later replaces that with the run's outcome. Only comment
// triggers react: a dispatch has no comment, and a skipped comment is left
// alone, so ordinary PR comments never collect reactions.
//
// Pure: bin/ocr-review does the GitHub calls.

// --- Constants --------------------------------------------------------------

/** The acknowledgement: the run is approved and under way. */
export const ACK_REACTION = 'eyes';

/** The outcome reaction for each record outcome (State Machine): success,
 * nothing-reviewable included, is +1; failure and cancellation are -1. */
const OUTCOME_REACTIONS = Object.freeze({ success: '+1', failure: '-1', cancelled: '-1' });

/** The login GITHUB_TOKEN reacts as: only its reactions are ever removed. */
export const WORKFLOW_LOGIN = 'github-actions[bot]';

/** A GitHub comment or reaction id: a positive decimal integer. */
const ID = /^[1-9][0-9]*$/;

// --- Predicates -------------------------------------------------------------

/** True when `value` can stand in a REST path as a comment or reaction id. */
export function isCommentId(value) {
  return typeof value === 'string' && ID.test(value);
}

// --- Pure helpers -----------------------------------------------------------

/** The reaction acknowledging a summon: eyes for an approved /ocr comment,
 * else null. */
export function ackReaction({ trigger, decision }) {
  return trigger === 'comment' && decision === 'approve' ? ACK_REACTION : null;
}

/** The reaction the report job leaves for a run's outcome: +1 or -1 on a
 * comment-triggered run, null for a dispatch or an unknown outcome. */
export function outcomeReaction({ trigger, outcome }) {
  if (trigger !== 'comment') return null;
  return Object.hasOwn(OUTCOME_REACTIONS, outcome) ? OUTCOME_REACTIONS[outcome] : null;
}

/** The ids of this workflow's own outcome reactions that contradict
 * `current` -- left by an earlier run on the same /ocr comment (a rerun) --
 * so the comment ends with one outcome, never both thumbs. Nobody else's
 * reaction, and no other content, is ever listed. */
export function staleOutcomeIds(reactions, current) {
  if (!Array.isArray(reactions)) return [];
  const outcomes = new Set(Object.values(OUTCOME_REACTIONS));
  return reactions
    .filter((r) => r?.user?.login === WORKFLOW_LOGIN && outcomes.has(r?.content) && r.content !== current)
    .map((r) => String(r.id))
    .filter(isCommentId);
}
