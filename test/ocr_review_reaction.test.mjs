// test/ocr_review_reaction.test.mjs -- OCR on Demand, the reactions on the
// triggering /ocr comment (docs/design/OCR-ON-DEMAND.DESIGN.md: Key
// Decisions, comment reactions row; owner request 2026-10-13). Which
// reaction, for which trigger and decision or outcome.
// Pure: values in, values out. No network.
// Run: node --test test/ocr_review_reaction.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ackReaction, isCommentId, outcomeReaction } from '../lib/ocr-review/reaction.mjs';

test('an approved /ocr comment is acknowledged with eyes', () => {
  assert.equal(ackReaction({ trigger: 'comment', decision: 'approve' }), 'eyes');
});

test('a skipped or failed comment, and every dispatch, gets no acknowledgement', () => {
  for (const decision of ['skip', 'fail', '', undefined]) assert.equal(ackReaction({ trigger: 'comment', decision }), null, String(decision));
  for (const decision of ['approve', 'skip', 'fail']) assert.equal(ackReaction({ trigger: 'dispatch', decision }), null, decision);
});

test('a comment or reaction id is a positive decimal integer and nothing else', () => {
  for (const ok of ['1', '1234567890', '987654321012']) assert.equal(isCommentId(ok), true, ok);
  for (const bad of ['', '0', '-1', '01', '12a', '1/../2', ' 1', undefined, null]) assert.equal(isCommentId(bad), false, String(bad));
});

test('a comment-triggered run ends with +1 on success, nothing-reviewable included', () => {
  // nothing-reviewable is outcome success with a cause; the cause does not change the reaction.
  assert.equal(outcomeReaction({ trigger: 'comment', outcome: 'success' }), '+1');
});

test('a comment-triggered run ends with -1 on failure (pr-not-open and fork included) or cancellation', () => {
  assert.equal(outcomeReaction({ trigger: 'comment', outcome: 'failure' }), '-1');
  assert.equal(outcomeReaction({ trigger: 'comment', outcome: 'cancelled' }), '-1');
});

test('a dispatch never reacts, and an outcome outside the record\'s set gets no reaction', () => {
  for (const outcome of ['success', 'failure', 'cancelled']) assert.equal(outcomeReaction({ trigger: 'dispatch', outcome }), null, outcome);
  for (const outcome of ['', 'skipped', undefined]) assert.equal(outcomeReaction({ trigger: 'comment', outcome }), null, String(outcome));
});
