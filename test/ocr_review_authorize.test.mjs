// test/ocr_review_authorize.test.mjs -- OCR on Demand, the authorize job's
// decision (docs/design/OCR-ON-DEMAND.DESIGN.md, G2 and the Authorize job
// table). Pure rules plus the one flow function, driven with a fake
// pull-request reader. No network.
// Run: node --test test/ocr_review_authorize.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  authorizeRun,
  isAuthorizedAssociation,
  isOcrCommand,
  judgePullRequest,
  screenTrigger,
} from '../lib/ocr-review/authorize.mjs';

const OPEN_PR = {
  state: 'open',
  headRepo: 'o/r',
  baseRepo: 'o/r',
  headSha: 'a'.repeat(40),
  baseRef: 'main',
};

const comment = (over) => ({ trigger: 'comment', commentBody: '/ocr', association: 'OWNER', pr: 7, ...over });
const dispatch = (over) => ({ trigger: 'dispatch', pr: 7, ...over });

/** A pull-request reader that answers from a table and records each read. */
function fakePulls(byNumber) {
  const reads = [];
  return {
    reads,
    readPullRequest: async (number) => {
      reads.push(number);
      return byNumber[number] ?? null;
    },
  };
}

test('a comment is an /ocr command only when its body starts with /ocr', () => {
  assert.equal(isOcrCommand('/ocr'), true);
  assert.equal(isOcrCommand('/ocr please look at the parser'), true);
  assert.equal(isOcrCommand('please /ocr'), false);
  assert.equal(isOcrCommand(' /ocr'), false);
  assert.equal(isOcrCommand('/OCR'), false);
  assert.equal(isOcrCommand(''), false);
  assert.equal(isOcrCommand(undefined), false);
});

test('only OWNER, MEMBER and COLLABORATOR may start a review by comment', () => {
  for (const ok of ['OWNER', 'MEMBER', 'COLLABORATOR']) assert.equal(isAuthorizedAssociation(ok), true, ok);
  for (const no of ['CONTRIBUTOR', 'FIRST_TIME_CONTRIBUTOR', 'FIRST_TIMER', 'MANNEQUIN', 'NONE', '', undefined]) {
    assert.equal(isAuthorizedAssociation(no), false, String(no));
  }
});

test('a comment that is not /ocr is skipped', () => {
  assert.equal(screenTrigger(comment({ commentBody: 'LGTM' })).decision, 'skip');
});

test('an /ocr comment from a non-collaborator is skipped', () => {
  assert.equal(screenTrigger(comment({ association: 'CONTRIBUTOR' })).decision, 'skip');
});

test('an /ocr comment from a collaborator proceeds to the pull-request checks', () => {
  assert.equal(screenTrigger(comment({ association: 'COLLABORATOR' })).decision, 'proceed');
});

test('a dispatch always proceeds: GitHub already required write access', () => {
  assert.equal(screenTrigger(dispatch()).decision, 'proceed');
});

test('a missing pull request (or an issue that is not one) fails pr-not-open', () => {
  const v = judgePullRequest(null);
  assert.equal(v.decision, 'fail');
  assert.equal(v.cause, 'pr-not-open');
});

test('a closed pull request fails pr-not-open', () => {
  const v = judgePullRequest({ ...OPEN_PR, state: 'closed' });
  assert.equal(v.decision, 'fail');
  assert.equal(v.cause, 'pr-not-open');
});

test('a fork head fails fork, including a head repo that no longer exists', () => {
  assert.equal(judgePullRequest({ ...OPEN_PR, headRepo: 'someone/r' }).cause, 'fork');
  assert.equal(judgePullRequest({ ...OPEN_PR, headRepo: null }).cause, 'fork');
});

test('repo names compare case-insensitively, as GitHub treats them', () => {
  assert.equal(judgePullRequest({ ...OPEN_PR, headRepo: 'O/R' }).decision, 'approve');
});

test('an open same-repo pull request is approved with its head and base', () => {
  const v = judgePullRequest(OPEN_PR);
  assert.equal(v.decision, 'approve');
  assert.equal(v.cause, null);
  assert.equal(v.headSha, OPEN_PR.headSha);
  assert.equal(v.baseRef, 'main');
});

test('authorizeRun: a skipped trigger never reads the pull request', async () => {
  const pulls = fakePulls({ 7: OPEN_PR });
  const v = await authorizeRun(comment({ commentBody: 'thanks!' }), pulls);
  assert.equal(v.decision, 'skip');
  assert.deepEqual(pulls.reads, []);
});

test('authorizeRun: an authorized /ocr on an issue that is not a PR fails pr-not-open', async () => {
  const v = await authorizeRun(comment({ pr: 9 }), fakePulls({ 7: OPEN_PR }));
  assert.equal(v.decision, 'fail');
  assert.equal(v.cause, 'pr-not-open');
});

test('authorizeRun: a dispatch for an open same-repo PR is approved', async () => {
  const pulls = fakePulls({ 7: OPEN_PR });
  const v = await authorizeRun(dispatch(), pulls);
  assert.equal(v.decision, 'approve');
  assert.deepEqual(pulls.reads, [7]);
});

test('authorizeRun: a non-positive or non-integer PR number is pr-not-open, never a read', async () => {
  for (const pr of [0, -1, 1.5, Number.NaN]) {
    const pulls = fakePulls({});
    const v = await authorizeRun(dispatch({ pr }), pulls);
    assert.equal(v.cause, 'pr-not-open', String(pr));
    assert.deepEqual(pulls.reads, []);
  }
});
