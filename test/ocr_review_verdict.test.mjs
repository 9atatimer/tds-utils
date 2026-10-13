// test/ocr_review_verdict.test.mjs -- OCR on Demand, the G4 verdict
// (docs/design/OCR-ON-DEMAND.DESIGN.md: G4, Review job table, Verdict row).
// Reviewable files are decided by this workflow from git's own facts about
// the range ocr resolved, never from ocr's selection; then compared with
// what ocr's result says it reviewed. Pure: no git, no network.
// Run: node --test test/ocr_review_verdict.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  LOCKFILES,
  isLockfile,
  judgeReview,
  parseCheckAttr,
  parseNameStatus,
  parseNumstat,
  readEngineResult,
  reviewableFiles,
} from '../lib/ocr-review/verdict.mjs';

const BASE = 'b'.repeat(40);
const HEAD = 'c'.repeat(40);

// --- git output parsers ------------------------------------------------------

test('name-status -z parses into status and path pairs', () => {
  assert.deepEqual(parseNameStatus('M\0src/a.js\0A\0src/new file.js\0D\0old.js\0'), [
    { status: 'M', path: 'src/a.js' },
    { status: 'A', path: 'src/new file.js' },
    { status: 'D', path: 'old.js' },
  ]);
  assert.deepEqual(parseNameStatus(''), []);
});

test('numstat -z marks the files git itself calls binary', () => {
  assert.deepEqual([...parseNumstat('3\t1\tsrc/a.js\0-\t-\tlogo.png\0')], ['logo.png']);
});

test('check-attr -z yields the generated and vendored paths', () => {
  const out = [
    'dist/x.js', 'linguist-generated', 'set',
    'dist/x.js', 'linguist-vendored', 'unspecified',
    'vendor/y.go', 'linguist-generated', 'unspecified',
    'vendor/y.go', 'linguist-vendored', 'true',
    'src/a.js', 'linguist-generated', 'false',
    'src/a.js', 'linguist-vendored', 'unset',
  ].join('\0') + '\0';
  const attrs = parseCheckAttr(out);
  assert.deepEqual(attrs.get('dist/x.js'), { generated: true, vendored: false });
  assert.deepEqual(attrs.get('vendor/y.go'), { generated: false, vendored: true });
  assert.deepEqual(attrs.get('src/a.js'), { generated: false, vendored: false });
});

// --- the exclusion class -----------------------------------------------------

test('lockfiles are a fixed list matched by file name in any directory', () => {
  for (const name of ['package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'Cargo.lock', 'go.sum', 'uv.lock', 'poetry.lock', 'Gemfile.lock']) {
    assert.ok(LOCKFILES.includes(name), name);
    assert.equal(isLockfile(`sub/dir/${name}`), true, name);
  }
  assert.equal(isLockfile('src/lock.js'), false);
  assert.equal(isLockfile('package.json'), false);
});

test('reviewable files exclude deleted, binary, generated, vendored and lockfiles', () => {
  const changes = [
    { status: 'M', path: 'src/a.js' },
    { status: 'A', path: 'src/b.js' },
    { status: 'D', path: 'src/gone.js' },
    { status: 'A', path: 'logo.png' },
    { status: 'M', path: 'dist/x.js' },
    { status: 'M', path: 'vendor/y.go' },
    { status: 'M', path: 'package-lock.json' },
  ];
  const binary = new Set(['logo.png']);
  const attributes = new Map([
    ['dist/x.js', { generated: true, vendored: false }],
    ['vendor/y.go', { generated: false, vendored: true }],
  ]);
  assert.deepEqual(reviewableFiles({ changes, binary, attributes }), ['src/a.js', 'src/b.js']);
});

test('no changes means no reviewable files (the empty accept case)', () => {
  assert.deepEqual(reviewableFiles({ changes: [], binary: new Set(), attributes: new Map() }), []);
});

// --- ocr's result --------------------------------------------------------------

const manifest = (over = {}) => ({
  schema_version: 'ocr.run-manifest/v1',
  terminal_state: 'complete',
  input: { mode: 'range', resolved_base: BASE, resolved_head: HEAD },
  coverage: {
    selected: [{ path: 'src/a.js' }, { path: 'src/b.js' }],
    completed: [{ path: 'src/a.js' }],
    reused: [{ path: 'src/b.js' }],
    failed: [],
    waived: [],
  },
  ...over,
});
const result = (over = {}) => JSON.stringify({ status: 'completed', comments: [{ path: 'src/a.js', start_line: 3, content: 'x' }], manifest: manifest(), ...over });

test('the engine result yields the resolved range, the reviewed files and the findings', () => {
  const r = readEngineResult(result());
  assert.equal(r.ok, true);
  assert.deepEqual(r.range, { base: BASE, head: HEAD });
  assert.deepEqual(r.reviewed, ['src/a.js', 'src/b.js']);
  assert.equal(r.findings.length, 1);
});

test('a null comments list is Go\'s empty slice: no findings, not a missing part', () => {
  const r = readEngineResult(result({ comments: null }));
  assert.equal(r.ok, true);
  assert.deepEqual(r.findings, []);
});

test('a missing or unparseable result, range or reviewed list is reported missing, never empty', () => {
  assert.deepEqual(readEngineResult('').missing, ['result']);
  assert.deepEqual(readEngineResult('{not json').missing, ['result']);
  assert.deepEqual(readEngineResult(result({ manifest: undefined })).missing.sort(), ['range', 'reviewed files']);
  assert.deepEqual(readEngineResult(result({ manifest: manifest({ input: { mode: 'range' } }) })).missing, ['range']);
  const noCoverage = manifest();
  delete noCoverage.coverage;
  assert.deepEqual(readEngineResult(result({ manifest: noCoverage })).missing, ['reviewed files']);
  assert.deepEqual(readEngineResult(result({ comments: undefined })).missing, ['findings']);
});

// --- the verdict ---------------------------------------------------------------

const engine = (reviewed, findings = []) => ({ ok: true, range: { base: BASE, head: HEAD }, reviewed, findings, missing: [] });
const finding = (path, line, content) => ({ path, start_line: line, content });

test('no per-finding post status is engine-error, never "nothing failed"', () => {
  const v = judgeReview({ reviewable: ['src/a.js'], engine: engine(['src/a.js']), postStatus: null });
  assert.equal(v.outcome, 'failure');
  assert.equal(v.cause, 'engine-error');
  assert.match(v.detail, /post status/);
});

test('a result missing the range or reviewed list is engine-error naming what is missing', () => {
  const v = judgeReview({ reviewable: ['src/a.js'], engine: { ok: false, missing: ['range'] }, postStatus: [] });
  assert.equal(v.cause, 'engine-error');
  assert.match(v.detail, /range/);
});

test('post status that does not line up with the findings is engine-error', () => {
  const v = judgeReview({ reviewable: ['src/a.js'], engine: engine(['src/a.js'], [finding('src/a.js', 1, 'x')]), postStatus: [] });
  assert.equal(v.cause, 'engine-error');
});

test('reviewable files exist and ocr reviewed none: reviewed-nothing', () => {
  const v = judgeReview({ reviewable: ['src/a.js', 'src/b.js'], engine: engine(['README.md']), postStatus: [] });
  assert.equal(v.outcome, 'failure');
  assert.equal(v.cause, 'reviewed-nothing');
  assert.equal(v.filesReviewable, 2);
  assert.equal(v.filesReviewed, 0);
});

test('some but not all reviewed: success listing every unreviewed reviewable file', () => {
  const v = judgeReview({ reviewable: ['src/a.js', 'src/b.js', 'src/c.js'], engine: engine(['src/a.js']), postStatus: [] });
  assert.equal(v.outcome, 'success');
  assert.equal(v.cause, null);
  assert.equal(v.filesReviewed, 1);
  assert.deepEqual(v.unreviewed, ['src/b.js', 'src/c.js']);
});

test('no reviewable files: success, files_reviewed 0, nothing-reviewable', () => {
  const v = judgeReview({ reviewable: [], engine: engine([]), postStatus: [] });
  assert.equal(v.outcome, 'success');
  assert.equal(v.cause, 'nothing-reviewable');
  assert.equal(v.filesReviewable, 0);
  assert.equal(v.filesReviewed, 0);
});

test('findings that failed to post or could not anchor are listed and counted; posted ones counted', () => {
  const findings = [finding('src/a.js', 1, 'one'), finding('src/a.js', 9, 'two'), finding('src/a.js', null, 'three')];
  const v = judgeReview({ reviewable: ['src/a.js'], engine: engine(['src/a.js'], findings), postStatus: ['inline', 'failed', 'unanchorable'] });
  assert.equal(v.outcome, 'success');
  assert.equal(v.findingsPosted, 1);
  assert.equal(v.findingsFailed, 1);
  assert.deepEqual(
    v.unposted.map((u) => [u.body, u.status]),
    [['two', 'failed'], ['three', 'unanchorable']],
  );
});

test('an unknown post status is engine-error, not silently dropped', () => {
  const v = judgeReview({ reviewable: ['src/a.js'], engine: engine(['src/a.js'], [finding('src/a.js', 1, 'x')]), postStatus: ['maybe'] });
  assert.equal(v.cause, 'engine-error');
});
