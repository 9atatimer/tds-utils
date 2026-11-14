// ocr_review_tier.test.mjs -- the review job's runner and time budgets,
// chosen from the PR's size (Issue#776, Issue#787): a large PR runs on the
// long niner (cf-pool-long, a 2-hour ceiling), every other PR on the medium
// niner (cf-pool-docker, 20 minutes) where the owner has set
// CI_RUNS_ON_DOCKER, else on the standard one.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { reviewPlan } from '../lib/ocr-review/tier.mjs';

const STANDARD = '["self-hosted","linux","x64","cf-pool"]';
const MEDIUM = '["self-hosted","linux","x64","cf-pool-docker"]';
const LONG = '["self-hosted","linux","x64","cf-pool-long"]';
// A repository with CI_RUNS_ON and CI_RUNS_ON_LONG but no CI_RUNS_ON_DOCKER:
// the plan before the medium tier, kept for an owner who has not set it.
const BASE = { changedFiles: '10', changedLines: '200', callerRunsOn: '', callerTimeout: '9', runsOn: STANDARD, runsOnDocker: '', runsOnLong: LONG, maxFiles: '', maxLines: '' };
const FLEET = { ...BASE, runsOnDocker: MEDIUM };

test('a small PR runs on the standard niner with the caller timeout', () => {
  assert.deepEqual(reviewPlan(BASE), {
    tier: 'standard', runsOn: STANDARD, timeoutMinutes: 9, stepTimeoutMinutes: 7, taskTimeoutMinutes: 7, note: '',
  });
});

test('with CI_RUNS_ON_DOCKER, a small PR runs on the medium niner, 19 minutes', () => {
  // misvtt PR#169 (7 files) timed out twice in the standard niner's 7-minute
  // task budget (Issue#787).
  assert.deepEqual(reviewPlan(FLEET), {
    tier: 'medium', runsOn: MEDIUM, timeoutMinutes: 19, stepTimeoutMinutes: 17, taskTimeoutMinutes: 15, note: '',
  });
});

test('the medium niner ignores the caller timeout meant for the standard one', () => {
  // Callers pass 9 whenever CI_RUNS_ON is set; that budget is the 10-minute
  // ceiling's, not the 20-minute one's.
  assert.equal(reviewPlan({ ...FLEET, callerTimeout: '9' }).timeoutMinutes, 19);
  assert.equal(reviewPlan({ ...FLEET, callerTimeout: '40' }).timeoutMinutes, 19);
});

test('a repository off the pool (no CI_RUNS_ON) stays GitHub-hosted with its own timeout', () => {
  // Nine-At-A-Time-Media sets CI_RUNS_ON_DOCKER and CI_RUNS_ON_LONG at org
  // level but not CI_RUNS_ON: its repositories run GitHub-hosted, where the
  // caller passes 40 minutes, more than the medium niner's 19.
  const plan = reviewPlan({ ...FLEET, runsOn: '', callerTimeout: '40' });
  assert.equal(plan.tier, 'standard');
  assert.equal(plan.runsOn, '"ubuntu-latest"');
  assert.equal(plan.timeoutMinutes, 40);
});

test('25 files is a large PR: the long niner, 115 minutes', () => {
  const plan = reviewPlan({ ...FLEET, changedFiles: '25' });
  assert.equal(plan.tier, 'long');
  assert.equal(plan.runsOn, LONG);
  assert.equal(plan.timeoutMinutes, 115);
});

test('24 files and 800 lines is still medium', () => {
  assert.equal(reviewPlan({ ...FLEET, changedFiles: '24', changedLines: '800' }).tier, 'medium');
});

test('a large PR with no CI_RUNS_ON_LONG goes to the medium niner and says why', () => {
  const plan = reviewPlan({ ...FLEET, changedFiles: '90', runsOnLong: '' });
  assert.equal(plan.tier, 'long');
  assert.equal(plan.runsOn, MEDIUM);
  assert.equal(plan.timeoutMinutes, 19);
  assert.match(plan.note, /CI_RUNS_ON_LONG is not set/);
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

test('just under both thresholds is still standard', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '24', changedLines: '800' }).tier, 'standard');
});

test('misvtt PR#88 (about 60 files, 2,000 lines) would have gone long', () => {
  assert.equal(reviewPlan({ ...BASE, changedFiles: '60', changedLines: '2000' }).tier, 'long');
});

test('the workflow default, 0, means the default thresholds, not "every PR is large"', () => {
  // long_review_files and long_review_lines default to 0 in the workflow.
  assert.equal(reviewPlan({ ...BASE, maxFiles: '0', maxLines: '0' }).tier, 'standard');
  assert.equal(reviewPlan({ ...BASE, changedFiles: '25', maxFiles: '0', maxLines: '0' }).tier, 'long');
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
