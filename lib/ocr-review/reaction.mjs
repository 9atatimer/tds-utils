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
