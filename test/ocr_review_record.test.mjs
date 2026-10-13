// test/ocr_review_record.test.mjs -- OCR on Demand, the report job's domain
// (docs/design/OCR-ON-DEMAND.DESIGN.md: State Machine, Data Model, Report
// job). How a run ended, the run record, and the one summary comment.
// Pure: values in, values out. No network.
// Run: node --test test/ocr_review_record.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CAUSES,
  RECORD_VERSION,
  buildRecord,
  endOfRun,
  isJudged,
  renderSummary,
  shouldComment,
  SUMMARY_MARKER,
} from '../lib/ocr-review/record.mjs';

const ok = (name, cause = null) => ({ name, outcome: 'success', cause });
const bad = (name, cause = null) => ({ name, outcome: 'failure', cause });
const skipped = (name) => ({ name, outcome: 'skipped', cause: null });

const approved = { result: 'success', decision: 'approve', cause: null, steps: [ok('Authorize')] };
const reviewOk = (verdictCause = null) => ({
  result: 'success',
  steps: [ok('Fetch the tools'), ok('Credentials'), ok('Probe'), ok('Review'), ok('Verdict', verdictCause)],
});

const RANGE = { base: 'b'.repeat(40), head: 'h'.repeat(40) };
const JUDGED = {
  range: RANGE,
  filesReviewable: 3,
  filesReviewed: 2,
  findingsPosted: 4,
  findingsFailed: 1,
  unreviewed: ['src/b.js'],
  unposted: [{ path: 'src/a.js', line: 3, status: 'failed', body: 'Null check missing.' }],
};

const baseFacts = {
  repo: 'o/r',
  pr: 7,
  trigger: 'dispatch',
  model: 'qwen3.6:latest',
  ocrVersion: '1.12.13',
  startedAt: '2026-10-12T10:00:00Z',
  finishedAt: '2026-10-12T10:05:00Z',
};

// --- endOfRun: the State Machine's terminal states --------------------------

test('a cancelled run ends cancelled, whatever the jobs did', () => {
  const end = endOfRun({ runCancelled: true, authorize: approved, review: { result: 'cancelled', steps: [] } });
  assert.deepEqual(end, { outcome: 'cancelled', cause: 'cancelled', failingStep: null });
});

test('authorize failing pr-not-open or fork ends with that cause', () => {
  for (const cause of ['pr-not-open', 'fork']) {
    const authorize = { result: 'failure', decision: 'fail', cause, steps: [bad('Authorize', cause)] };
    const end = endOfRun({ runCancelled: false, authorize, review: { result: 'skipped', steps: [] } });
    assert.deepEqual(end, { outcome: 'failure', cause, failingStep: null });
  }
});

test('a step that declares its cause ends the run with it (configuration, probe causes, engine-error)', () => {
  for (const [step, cause] of [
    ['Credentials', 'configuration'],
    ['Probe', 'credential'],
    ['Probe', 'gateway-down'],
    ['Probe', 'model-not-found'],
    ['Probe', 'cold-model'],
    ['Review', 'engine-error'],
    ['Verdict', 'engine-error'],
    ['Verdict', 'reviewed-nothing'],
  ]) {
    const steps = [ok('Fetch the tools'), step === 'Credentials' ? bad(step, cause) : ok('Credentials')];
    if (step !== 'Credentials') steps.push(bad(step, cause));
    const end = endOfRun({ runCancelled: false, authorize: approved, review: { result: 'failure', steps } });
    assert.deepEqual(end, { outcome: 'failure', cause, failingStep: null }, `${step}/${cause}`);
  }
});

test('a probe answer nobody documented is unexpected and names the probe step', () => {
  const steps = [ok('Credentials'), bad('Probe', 'unexpected')];
  const end = endOfRun({ runCancelled: false, authorize: approved, review: { result: 'failure', steps } });
  assert.deepEqual(end, { outcome: 'failure', cause: 'unexpected', failingStep: 'review / Probe' });
});

test('a step that fails without a cause of its own is unexpected, naming job and step', () => {
  const steps = [bad('Install the 1Password CLI'), skipped('Credentials')];
  const end = endOfRun({ runCancelled: false, authorize: approved, review: { result: 'failure', steps } });
  assert.deepEqual(end, { outcome: 'failure', cause: 'unexpected', failingStep: 'review / Install the 1Password CLI' });
});

test('an authorize job that crashed before deciding is unexpected, naming its step', () => {
  const authorize = { result: 'failure', decision: '', cause: null, steps: [bad('Authorize')] };
  const end = endOfRun({ runCancelled: false, authorize, review: { result: 'skipped', steps: [] } });
  assert.deepEqual(end, { outcome: 'failure', cause: 'unexpected', failingStep: 'authorize / Authorize' });
});

test('a job that ended badly with no failed step (a timeout) is unexpected, naming the job', () => {
  const end = endOfRun({ runCancelled: false, authorize: approved, review: { result: 'cancelled', steps: [ok('Credentials')] } });
  assert.equal(end.outcome, 'failure');
  assert.equal(end.cause, 'unexpected');
  assert.match(end.failingStep, /^review \/ .*timeout/);
});

test('a cause outside the closed set is never passed through: it becomes unexpected', () => {
  const steps = [bad('Probe', 'made-up')];
  const end = endOfRun({ runCancelled: false, authorize: approved, review: { result: 'failure', steps } });
  assert.equal(end.cause, 'unexpected');
  assert.equal(end.failingStep, 'review / Probe');
});

test('a successful review ends success with the verdict cause (null or nothing-reviewable)', () => {
  assert.deepEqual(endOfRun({ runCancelled: false, authorize: approved, review: reviewOk() }), {
    outcome: 'success',
    cause: null,
    failingStep: null,
  });
  assert.deepEqual(endOfRun({ runCancelled: false, authorize: approved, review: reviewOk('nothing-reviewable') }), {
    outcome: 'success',
    cause: 'nothing-reviewable',
    failingStep: null,
  });
});

test('every cause the State Machine names is in the closed set', () => {
  for (const c of [
    'pr-not-open',
    'fork',
    'configuration',
    'credential',
    'gateway-down',
    'model-not-found',
    'cold-model',
    'unexpected',
    'engine-error',
    'reviewed-nothing',
    'nothing-reviewable',
    'cancelled',
  ]) {
    assert.ok(CAUSES.includes(c), c);
  }
});

// --- buildRecord: the Data Model --------------------------------------------

const RECORD_KEYS = [
  'record_version',
  'repo',
  'pr',
  'trigger',
  'head_sha',
  'range',
  'model',
  'ocr_version',
  'outcome',
  'cause',
  'failing_step',
  'files_reviewable',
  'files_reviewed',
  'findings_posted',
  'findings_failed',
  'started_at',
  'finished_at',
];

test('a judged success carries every Data Model field', () => {
  const r = buildRecord({ ...baseFacts, approved: true, end: { outcome: 'success', cause: null, failingStep: null }, judged: JUDGED });
  assert.deepEqual(Object.keys(r).sort(), [...RECORD_KEYS].sort());
  assert.equal(r.record_version, RECORD_VERSION);
  assert.equal(r.head_sha, RANGE.head);
  assert.equal(r.range, `${RANGE.base}..${RANGE.head}`);
  assert.equal(r.files_reviewable, 3);
  assert.equal(r.files_reviewed, 2);
  assert.equal(r.findings_posted, 4);
  assert.equal(r.findings_failed, 1);
  assert.equal(r.failing_step, null);
});

test('a run that ended at authorize has null head, range, model, ocr_version and counts', () => {
  const r = buildRecord({
    ...baseFacts,
    model: null,
    approved: false,
    end: { outcome: 'failure', cause: 'pr-not-open', failingStep: null },
    judged: null,
  });
  for (const k of ['head_sha', 'range', 'model', 'ocr_version', 'files_reviewable', 'files_reviewed', 'findings_posted', 'findings_failed']) {
    assert.equal(r[k], null, k);
  }
  assert.equal(r.repo, 'o/r');
  assert.equal(r.pr, 7);
  assert.equal(r.trigger, 'dispatch');
  assert.ok(r.started_at && r.finished_at);
});

test('an engine-error run keeps the model and ocr_version but has null counts', () => {
  const r = buildRecord({ ...baseFacts, approved: true, end: { outcome: 'failure', cause: 'engine-error', failingStep: null }, judged: null });
  assert.equal(r.model, 'qwen3.6:latest');
  assert.equal(r.ocr_version, '1.12.13');
  assert.equal(r.files_reviewed, null);
  assert.equal(r.range, null);
});

test('failing_step is set only for unexpected', () => {
  const r = buildRecord({
    ...baseFacts,
    approved: true,
    end: { outcome: 'failure', cause: 'unexpected', failingStep: 'review / Probe' },
    judged: null,
  });
  assert.equal(r.failing_step, 'review / Probe');
});

test('isJudged: only a verdict that reached JUDGED counts', () => {
  assert.equal(isJudged({ outcome: 'success', cause: null }), true);
  assert.equal(isJudged({ outcome: 'success', cause: 'nothing-reviewable' }), true);
  assert.equal(isJudged({ outcome: 'failure', cause: 'reviewed-nothing' }), true);
  assert.equal(isJudged({ outcome: 'failure', cause: 'engine-error' }), false);
  assert.equal(isJudged({ outcome: 'cancelled', cause: 'cancelled' }), false);
});

// --- Summary comment ----------------------------------------------------------

const record = (over) =>
  buildRecord({ ...baseFacts, approved: true, end: { outcome: 'success', cause: null, failingStep: null }, judged: JUDGED, ...over });

test('every terminal state comments except pr-not-open', () => {
  assert.equal(shouldComment({ cause: 'pr-not-open' }), false);
  for (const cause of CAUSES.filter((c) => c !== 'pr-not-open')) assert.equal(shouldComment({ cause }), true, cause);
  assert.equal(shouldComment({ cause: null }), true);
});

test('a success summary names the range, the counts, the unreviewed files and the unposted findings', () => {
  const body = renderSummary(record(), { runUrl: 'https://github.com/o/r/actions/runs/1', judged: JUDGED });
  assert.ok(body.startsWith(SUMMARY_MARKER));
  assert.match(body, new RegExp(`${RANGE.base.slice(0, 7)}\\.\\.${RANGE.head.slice(0, 7)}`));
  assert.match(body, /2 of 3 reviewable files/);
  assert.match(body, /src\/b\.js/);
  assert.match(body, /src\/a\.js/);
  assert.match(body, /Null check missing\./);
  assert.match(body, /actions\/runs\/1/);
});

test('a nothing-reviewable summary says so', () => {
  const judged = { ...JUDGED, filesReviewable: 0, filesReviewed: 0, unreviewed: [], unposted: [] };
  const body = renderSummary(record({ end: { outcome: 'success', cause: 'nothing-reviewable', failingStep: null }, judged }), {
    runUrl: 'u',
    judged,
  });
  assert.match(body, /no reviewable files/i);
});

test('a failure summary names the cause; unexpected also names the failing step', () => {
  const fail = renderSummary(record({ end: { outcome: 'failure', cause: 'gateway-down', failingStep: null }, judged: null }), {
    runUrl: 'u',
    detail: 'HTTP 502 from the gateway',
  });
  assert.match(fail, /gateway-down/);
  assert.match(fail, /HTTP 502 from the gateway/);
  const unexpected = renderSummary(record({ end: { outcome: 'failure', cause: 'unexpected', failingStep: 'review / Probe' }, judged: null }), {
    runUrl: 'u',
  });
  assert.match(unexpected, /review \/ Probe/);
});

test('a cancelled summary says the run was cancelled', () => {
  const body = renderSummary(record({ end: { outcome: 'cancelled', cause: 'cancelled', failingStep: null }, judged: null }), { runUrl: 'u' });
  assert.match(body, /cancelled/i);
});

test('PR-controlled text cannot break out of its block or mention anyone', () => {
  const judged = {
    ...JUDGED,
    unreviewed: ['evil`path`@team.js'],
    unposted: [{ path: 'x.js', line: 1, status: 'failed', body: '```\n@everyone ping <img src=x>\n```' }],
  };
  const body = renderSummary(record({ judged }), { runUrl: 'u', judged });
  // The finding sits inside a fence longer than any backtick run it holds,
  // so its own ``` cannot close the block and its @mention is inert text.
  const fenced = body.match(/^(`{4,})\n([\s\S]*?)\n\1$/m);
  assert.ok(fenced, 'finding body is fenced with a fence longer than its own backticks');
  assert.match(fenced[2], /@everyone ping/);
  assert.equal(body.split('@everyone').length, 2, '@everyone appears once, inside the fence');
  // A path is HTML-escaped inside <code>, so backticks and @ are inert.
  assert.match(body, /<code>evil&#96;path&#96;&#64;team\.js<\/code>/);
});
