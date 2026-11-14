// ocr_review_tier.test.mjs -- the review job's runner and time budgets,
// chosen from the PR's size (Issue#776): a large PR runs on the long niner
// (cf-pool-long, a 2-hour ceiling), every other PR keeps the standard one.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { reviewPlan } from '../lib/ocr-review/tier.mjs';

const STANDARD = '["self-hosted","linux","x64","cf-pool"]';
const LONG = '["self-hosted","linux","x64","cf-pool-long"]';
const BASE = { changedFiles: '10', changedLines: '200', callerRunsOn: '', callerTimeout: '9', runsOn: STANDARD, runsOnLong: LONG, maxFiles: '', maxLines: '' };

test('a small PR runs on the standard niner with the caller timeout', () => {
  assert.deepEqual(reviewPlan(BASE), {
    tier: 'standard', runsOn: STANDARD, timeoutMinutes: 9, stepTimeoutMinutes: 7, taskTimeoutMinutes: 7, note: '',
  });
});

test('more than 25 files is a large PR: the long niner, 115 minutes', () => {
  const plan = reviewPlan({ ...BASE, changedFiles: '26' });
  assert.equal(plan.tier, 'long');
  assert.equal(plan.runsOn, LONG);
  assert.equal(plan.timeoutMinutes, 115);
  assert.equal(plan.stepTimeoutMinutes, 113);
});

test('more than 800 changed lines is a large PR too', () => {
  assert.equal(reviewPlan({ ...BASE, changedLines: '801' }).tier, 'long');
});

test('exactly at both thresholds is still standard', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '25', changedLines: '800' }).tier, 'standard');
});

test('misvtt PR#88 (about 60 files, 2,000 lines) would have gone long', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '60', changedLines: '2000' }).tier, 'long');
});

test('the workflow default, 0, means the default thresholds, not "every PR is large"', () => {
  // long_review_files and long_review_lines default to 0 in the workflow.
  assert.equal(reviewPlan({ ...BASE, maxFiles: '0', maxLines: '0' }).tier, 'standard');
  assert.equal(reviewPlan({ ...BASE, changedFiles: '26', maxFiles: '0', maxLines: '0' }).tier, 'long');
});

test('a caller may set its own thresholds', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '10', maxFiles: '5' }).tier, 'long');
  assert.equal(reviewPlan({ ...BASE, changedFiles: '30', maxFiles: '50' }).tier, 'standard');
});

test('an unknown size is standard, never long', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '', changedLines: '' }).tier, 'standard');
});

test('a caller that names its own runner keeps it and its own timeout, whatever the size', () => {
  const docker = '["self-hosted","cf-pool-docker"]';
  const plan = reviewPlan({ ...BASE, changedFiles: '90', callerRunsOn: docker, callerTimeout: '19' });
  assert.equal(plan.runsOn, docker);
  assert.equal(plan.timeoutMinutes, 19);
  assert.equal(plan.note, '');
});

test('a large PR with no CI_RUNS_ON_LONG stays on the standard runner and says why', () => {
  const plan = reviewPlan({ ...BASE, changedFiles: '90', runsOnLong: '' });
  assert.equal(plan.tier, 'long');
  assert.equal(plan.runsOn, STANDARD);
  assert.equal(plan.timeoutMinutes, 9);
  assert.match(plan.note, /CI_RUNS_ON_LONG is not set/);
});

test('with no CI_RUNS_ON at all, a standard review runs GitHub-hosted', () => {
  assert.equal(reviewPlan({ ...BASE, runsOn: '' }).runsOn, '"ubuntu-latest"');
});

test('the task budget never exceeds the step, and never the upstream 15', () => {
  assert.equal(reviewPlan(BASE).taskTimeoutMinutes, 7);
  assert.equal(reviewPlan({ ...BASE, changedFiles: '90' }).taskTimeoutMinutes, 15);
  assert.equal(reviewPlan({ ...BASE, callerTimeout: '3' }).taskTimeoutMinutes, 1);
});

test('a missing, zero or bad caller timeout falls back to 9, with its budgets', () => {
  for (const callerTimeout of ['', '0', 'soon']) {
    const plan = reviewPlan({ ...BASE, callerTimeout });
    assert.equal(plan.timeoutMinutes, 9, callerTimeout);
    assert.equal(plan.stepTimeoutMinutes, 7, callerTimeout);
    assert.equal(plan.taskTimeoutMinutes, 7, callerTimeout);
  }
});
