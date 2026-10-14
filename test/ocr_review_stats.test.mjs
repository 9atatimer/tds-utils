// test/ocr_review_stats.test.mjs -- OCR on Demand, bin/ocr-review-stats
// (docs/design/OCR-ON-DEMAND.DESIGN.md: G7, Design/Stats, Data Warehouse;
// Key Decisions Q2: 90-day artifacts). Runs by outcome and failures by cause,
// per period, across adopting repos, for every record_version. Pure rules
// plus the collect flow against a fake GitHub port. No network.
// Run: node --test test/ocr_review_stats.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { aggregate, normalizeRecord, periodKey, renderTable } from '../lib/ocr-review/stats.mjs';
import { collectStats } from '../bin/ocr-review-stats';

const v1 = (over) => ({
  record_version: 1,
  repo: 'o/r',
  pr: 1,
  trigger: 'dispatch',
  outcome: 'success',
  cause: null,
  started_at: '2026-10-05T10:00:00Z',
  finished_at: '2026-10-05T10:04:00Z',
  ...over,
});

test('periods: day, ISO week (Monday start) and month', () => {
  assert.equal(periodKey('2026-10-07T23:59:00Z', 'day'), '2026-10-07');
  assert.equal(periodKey('2026-10-07T12:00:00Z', 'week'), '2026-10-05');
  assert.equal(periodKey('2026-10-05T00:00:00Z', 'week'), '2026-10-05');
  assert.equal(periodKey('2026-10-04T23:00:00Z', 'week'), '2026-09-28');
  assert.equal(periodKey('2026-10-31T23:00:00Z', 'month'), '2026-10');
});

test('a version 1 record normalizes to repo, outcome, cause and time', () => {
  assert.deepEqual(normalizeRecord(v1({ outcome: 'failure', cause: 'gateway-down' })), {
    ok: true,
    version: 1,
    repo: 'o/r',
    outcome: 'failure',
    cause: 'gateway-down',
    at: '2026-10-05T10:04:00Z',
  });
});

test('an unknown record_version, or an unreadable record, is reported, never misread', () => {
  assert.deepEqual(normalizeRecord({ record_version: 99, outcome: 'success' }), { ok: false, reason: 'record_version 99 is unknown' });
  assert.equal(normalizeRecord(null).ok, false);
  assert.equal(normalizeRecord(v1({ outcome: 'exploded' })).ok, false);
});

test('aggregate counts runs by outcome and failures by cause, per period', () => {
  const records = [
    v1({}),
    v1({ outcome: 'failure', cause: 'gateway-down' }),
    v1({ outcome: 'failure', cause: 'gateway-down', finished_at: '2026-10-06T00:00:00Z' }),
    v1({ outcome: 'cancelled', cause: 'cancelled' }),
    v1({ outcome: 'failure', cause: 'engine-error', finished_at: '2026-10-13T09:00:00Z' }),
  ].map(normalizeRecord);
  const rows = aggregate(records, 'week');
  assert.deepEqual(rows, [
    { period: '2026-10-05', runs: 4, success: 1, failure: 2, cancelled: 1, causes: { 'gateway-down': 2 } },
    { period: '2026-10-12', runs: 1, success: 0, failure: 1, cancelled: 0, causes: { 'engine-error': 1 } },
  ]);
});

test('no records is an empty report, not an error (the empty accept case)', () => {
  assert.deepEqual(aggregate([], 'week'), []);
  assert.match(renderTable([], { unreadable: 0, unrecorded: 0 }), /no run records/i);
});

test('the table shows each period, its outcomes, its failure causes, and what could not be read', () => {
  const rows = aggregate([v1({}), v1({ outcome: 'failure', cause: 'cold-model' })].map(normalizeRecord), 'week');
  const table = renderTable(rows, { unreadable: 1, unrecorded: 2 });
  assert.match(table, /2026-10-05/);
  assert.match(table, /cold-model\s+1/);
  assert.match(table, /unreadable records: 1/);
  assert.match(table, /runs without a record.*: 2/);
});

test('a runner-tool-missing failure is counted and shown under its own cause, at full width', () => {
  const rows = aggregate([v1({ outcome: 'failure', cause: 'runner-tool-missing' })].map(normalizeRecord), 'week');
  assert.deepEqual(rows[0].causes, { 'runner-tool-missing': 1 });
  assert.match(renderTable(rows, { unreadable: 0, unrecorded: 0 }), /^ {2}runner-tool-missing\s+1$/m);
});

// --- collect flow ----------------------------------------------------------------

/** A fake GitHub port: adopters per owner, runs per repo, records per run. */
function fakeGithub({ adopters = {}, runs = {}, records = {} }) {
  const calls = [];
  return {
    calls,
    listAdopters: async (owner) => {
      calls.push(['adopters', owner]);
      return adopters[owner] ?? [];
    },
    listRuns: async (repo, since) => {
      calls.push(['runs', repo, since]);
      return runs[repo] ?? [];
    },
    readRecords: async (repo, runId) => {
      calls.push(['records', repo, runId]);
      return records[`${repo}#${runId}`] ?? [];
    },
  };
}

test('collect reads every adopter of every owner, since the window start, and counts unrecorded runs', async () => {
  const github = fakeGithub({
    adopters: { a: ['a/one'], b: ['b/two'] },
    runs: { 'a/one': [{ id: 1 }, { id: 2 }], 'b/two': [{ id: 3 }] },
    records: {
      'a/one#1': [JSON.stringify(v1({ repo: 'a/one' }))],
      'b/two#3': [JSON.stringify(v1({ repo: 'b/two', outcome: 'failure', cause: 'credential' })), '{garbage'],
    },
  });
  const result = await collectStats({ owners: ['a', 'b'], repos: [], since: '2026-07-14T00:00:00Z' }, { github });
  assert.equal(result.records.length, 2);
  assert.equal(result.unrecorded, 1, 'run 2 left no record (skipped, or its report failed)');
  assert.equal(result.unreadable, 1);
  assert.ok(github.calls.some((c) => c[0] === 'runs' && c[2] === '2026-07-14T00:00:00Z'));
});

test('collect with named repos reads only those, never discovering adopters', async () => {
  const github = fakeGithub({ runs: { 'x/y': [] } });
  await collectStats({ owners: ['a'], repos: ['x/y'], since: 's' }, { github });
  assert.deepEqual(
    github.calls.map((c) => c[0]),
    ['runs'],
  );
});

test('collect never writes: its port has only reads', async () => {
  const github = fakeGithub({});
  await collectStats({ owners: ['a'], repos: [], since: 's' }, { github });
  assert.ok(github.calls.every((c) => ['adopters', 'runs', 'records'].includes(c[0])));
});

test('a record_version 2 record (it names the backend) is read like version 1', () => {
  const r = normalizeRecord(v1({ record_version: 2, backend: 'cf-ai-gateway' }));
  assert.equal(r.ok, true);
  assert.equal(r.version, 2);
  assert.equal(r.outcome, 'success');
});
