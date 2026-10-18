// test/ocr_bakeoff.test.mjs -- the OCR bake-off (tds-utils Issue#468): which
// model reviews best, measured on diffs Copilot or Codex reviewed and the
// findings on them that triage accepted. The rules (lib/ocr-bakeoff), the
// step commands (bin/ocr-bakeoff, against fake ports) and the workflow
// file's wiring. No network.
// Run: node --test test/ocr_bakeoff.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  MAX_JOBS,
  buildMatrix,
  buildRunRecord,
  collate,
  configArgs,
  locate,
  parseCases,
  parseModels,
  renderReport,
  reviewArgs,
  selectCases,
} from '../lib/ocr-bakeoff/bakeoff.mjs';
import { runCollate, runMatrix, runReview } from '../bin/ocr-bakeoff';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SHA_A = 'a'.repeat(40);
const SHA_B = 'b'.repeat(40);

const kase = (over) => ({
  id: 'tt1-aaaaaaa',
  repo: 'o/r',
  pr: 1,
  base: SHA_A,
  head: SHA_B,
  accepted: [{ path: 'x.sh', line: 10, start_line: null, reviewer: 'copilot', url: 'u', summary: 's' }],
  ...over,
});

const result = (comments, completed = [{ path: 'x.sh' }]) =>
  JSON.stringify({
    manifest: { input: { resolved_base: SHA_A, resolved_head: SHA_B }, coverage: { completed, reused: [] } },
    comments,
  });

// --- Cases and models -------------------------------------------------------

test('the committed cases parse, and every case has a base, a head and accepted findings', () => {
  const cases = parseCases(readFileSync(join(ROOT, 'lib/ocr-bakeoff/cases.json'), 'utf8'));
  assert.ok(cases.length >= 1);
  for (const c of cases) {
    assert.match(c.base, /^[0-9a-f]{40}$/);
    assert.match(c.head, /^[0-9a-f]{40}$/);
    assert.ok(c.accepted.length >= 1, c.id);
  }
  assert.equal(new Set(cases.map((c) => c.id)).size, cases.length, 'case ids are unique');
});

test('cases: every accepted finding carries its defect text, not only a title or a badge', () => {
  const cases = parseCases(readFileSync(join(ROOT, 'lib/ocr-bakeoff/cases.json'), 'utf8'));
  for (const c of cases) {
    for (const a of c.accepted) {
      assert.doesNotMatch(a.summary, /<sub>|!\[/, `${a.url}: markup`);
      assert.ok(a.summary.length >= 120, `${a.url}: ${a.summary.length} chars`);
    }
  }
});

test('cases: a case without a full base SHA, or a duplicate id, is refused', () => {
  const doc = (cases) => JSON.stringify({ cases });
  assert.throws(() => parseCases(doc([kase({ base: 'abc' })])), /base/);
  assert.throws(() => parseCases(doc([kase(), kase()])), /duplicate/);
  assert.throws(() => parseCases('{'), /cases/);
});

test('models: one per line or comma, trimmed, deduplicated, order kept', () => {
  assert.deepEqual(parseModels('qwen3.6:latest\n hf.co/u/M-GGUF:Q6_K ,qwen3.6:latest\n\n'), [
    'qwen3.6:latest',
    'hf.co/u/M-GGUF:Q6_K',
  ]);
});

test('models: none, or a name outside the model-name alphabet, is refused', () => {
  assert.throws(() => parseModels(' \n'), /no model/);
  assert.throws(() => parseModels('a;rm -rf'), /model name/);
  assert.throws(() => parseModels('$(x)'), /model name/);
});

test('cases filter: empty selects all; an unknown id is refused', () => {
  const all = [kase({ id: 'c1' }), kase({ id: 'c2' })];
  assert.deepEqual(selectCases(all, '').map((c) => c.id), ['c1', 'c2']);
  assert.deepEqual(selectCases(all, ' c2 ').map((c) => c.id), ['c2']);
  assert.throws(() => selectCases(all, 'c3'), /unknown case: c3/);
});

// --- Matrix -----------------------------------------------------------------

test('matrix: model-major, so each model loads once and its first case is the cold one', () => {
  const m = buildMatrix(['m-one', 'm-two'], [kase({ id: 'c1' }), kase({ id: 'c2' })]);
  assert.deepEqual(
    m.include.map((e) => [e.key, e.model, e.case]),
    [
      ['m1-c1', 'm-one', 'c1'],
      ['m1-c2', 'm-one', 'c2'],
      ['m2-c1', 'm-two', 'c1'],
      ['m2-c2', 'm-two', 'c2'],
    ],
  );
  assert.equal(m.include[0].first_for_model, true);
  assert.equal(m.include[1].first_for_model, false);
  assert.equal(m.include[0].base, SHA_A);
  assert.equal(m.include[0].head, SHA_B);
});

test('matrix: more jobs than GitHub allows in one matrix is refused, not truncated', () => {
  const many = Array.from({ length: MAX_JOBS + 1 }, (_, i) => kase({ id: `c${i}` }));
  assert.throws(() => buildMatrix(['m'], many), /jobs/);
});

// --- ocr invocation ---------------------------------------------------------

test('review args: the range, agent JSON and the per-task timeout OCR on Demand uses', () => {
  assert.deepEqual(reviewArgs({ base: SHA_A, head: SHA_B }), [
    'review',
    '--from',
    SHA_A,
    '--to',
    SHA_B,
    '--audience',
    'agent',
    '--format',
    'json',
    '--timeout',
    '15',
  ]);
});

// --- Scoring ----------------------------------------------------------------

test('locate: same path and a line within the window counts; another file or a far line does not', () => {
  const accepted = [
    { path: 'x.sh', line: 10, start_line: null },
    { path: 'y.ts', line: 100, start_line: 90 },
    { path: 'z.mjs', line: 5, start_line: null },
  ];
  const findings = [
    { path: 'x.sh', start_line: 18, end_line: 19 },
    { path: 'y.ts', start_line: 70, end_line: 85 },
    { path: 'other.mjs', start_line: 5 },
    { path: 'z.mjs', start_line: 40 },
  ];
  assert.deepEqual(locate(accepted, findings), [true, true, false]);
});

test('locate: a finding without a line never locates', () => {
  assert.deepEqual(locate([{ path: 'x.sh', line: 10 }], [{ path: 'x.sh' }]), [false]);
  assert.deepEqual(locate([{ path: 'x.sh', line: 3 }], [{ path: 'x.sh', start_line: 0, end_line: 0 }]), [false], 'ocr writes 0 for no line');
});

test('run record: a completed review carries findings, coverage, located and timings', () => {
  const rec = buildRunRecord({
    entry: { key: 'm1-c1', model: 'm', case: 'c1', first_for_model: true },
    kase: kase({ id: 'c1' }),
    exit: { code: 0, timedOut: false },
    resultText: result([{ path: 'x.sh', start_line: 12, content: 'bug', severity: 'high', category: 'bug' }]),
    probeSeconds: 41,
    reviewSeconds: 120,
  });
  assert.equal(rec.outcome, 'complete');
  assert.equal(rec.findings_total, 1);
  assert.deepEqual(rec.located, [true]);
  assert.deepEqual(rec.files_reviewed, ['x.sh']);
  assert.equal(rec.probe_seconds, 41);
  assert.equal(rec.review_seconds, 120);
  assert.equal(rec.cold, true);
  assert.equal(rec.findings[0].content, 'bug');
});

test('run record: the deadline is timeout; a non-zero exit or an unreadable result is engine-error', () => {
  const base = { entry: { key: 'k', model: 'm', case: 'c1', first_for_model: false }, kase: kase({ id: 'c1' }), probeSeconds: 1, reviewSeconds: 2 };
  assert.equal(buildRunRecord({ ...base, exit: { code: null, timedOut: true }, resultText: '' }).outcome, 'timeout');
  assert.equal(buildRunRecord({ ...base, exit: { code: 1, timedOut: false }, resultText: result([]) }).outcome, 'engine-error');
  const unreadable = buildRunRecord({ ...base, exit: { code: 0, timedOut: false }, resultText: '{}' });
  assert.equal(unreadable.outcome, 'engine-error');
  assert.match(unreadable.detail, /range/);
  for (const r of [unreadable]) assert.deepEqual(r.located, [false]);
});

// --- Collation --------------------------------------------------------------

test('collate: per model, runs, outcomes, located k of n and timings; a missing run is no-record', () => {
  const cases = [kase({ id: 'c1' }), kase({ id: 'c2', accepted: [{ path: 'a', line: 1 }, { path: 'b', line: 2 }] })];
  const records = [
    { record_version: 1, key: 'm1-c1', model: 'm-one', case: 'c1', outcome: 'complete', located: [true], findings_total: 3, probe_seconds: 50, review_seconds: 100, cold: true },
    { record_version: 1, key: 'm1-c2', model: 'm-one', case: 'c2', outcome: 'timeout', located: [false, false], findings_total: 0, probe_seconds: 5, review_seconds: 400, cold: false },
    { record_version: 1, key: 'm2-c1', model: 'm-two', case: 'c1', outcome: 'complete', located: [false], findings_total: 1, probe_seconds: 60, review_seconds: 80, cold: true },
  ];
  const { rows, missing } = collate(records, { models: ['m-one', 'm-two'], cases });
  const one = rows.find((r) => r.model === 'm-one');
  assert.equal(one.runs, 2);
  assert.equal(one.complete, 1);
  assert.deepEqual(one.failures, { timeout: 1 });
  assert.equal(one.located, 1);
  assert.equal(one.accepted, 3);
  assert.equal(one.findings, 3);
  assert.equal(one.cold_probe_seconds, 50);
  const two = rows.find((r) => r.model === 'm-two');
  assert.deepEqual(two.failures, { 'no-record': 1 });
  assert.equal(two.accepted, 3, 'a missing run still counts its accepted findings as not located');
  assert.deepEqual(missing, ['m2-c2']);
});

test('report: one row per model, located k/n, and every missing run named', () => {
  const text = renderReport({
    rows: [{ model: 'm-one', runs: 2, complete: 1, failures: { timeout: 1 }, located: 1, accepted: 3, findings: 3, cold_probe_seconds: 50, median_review_seconds: 250 }],
    missing: ['m2-c2'],
  });
  assert.match(text, /\| m-one \| 2 \| 1 \| timeout 1 \| 1 \/ 3 \| 3 \| 50 \| 250 \|/);
  assert.match(text, /m2-c2/);
});

// --- Step commands, against fake ports --------------------------------------

function fakeStep() {
  const outputs = {};
  const logs = [];
  const files = {};
  return {
    outputs,
    logs,
    files,
    log: (l) => logs.push(l),
    setOutput: (k, v) => {
      outputs[k] = String(v);
    },
    writeFile: (p, t) => {
      files[p] = t;
    },
  };
}

test('matrix step: writes the matrix and its size; refuses a bad model list with exit 1', () => {
  const step = fakeStep();
  const casesText = JSON.stringify({ cases: [kase({ id: 'c1' }), kase({ id: 'c2' })] });
  assert.equal(runMatrix({ env: { MODELS: 'a\nb', CASES: '' }, casesText, step }), 0);
  assert.equal(JSON.parse(step.outputs.matrix).include.length, 4);
  assert.equal(step.outputs.count, '4');
  const bad = fakeStep();
  assert.equal(runMatrix({ env: { MODELS: 'a;b', CASES: '' }, casesText, step: bad }), 1);
  assert.match(bad.logs.join('\n'), /::error::/);
});

test('review step: configures ocr like OCR on Demand, runs the case range, and writes the record', async () => {
  const calls = [];
  const step = fakeStep();
  const run = async (cmd, argv, opts) => {
    calls.push({ cmd, argv, env: opts.env, cwd: opts.cwd, deadlineMs: opts.deadlineMs });
    if (argv[0] === 'review') return { code: 0, timedOut: false, stdout: result([{ path: 'x.sh', start_line: 9 }]) };
    return { code: 0, timedOut: false, stdout: '' };
  };
  const now = (() => {
    let t = 1000;
    return () => (t += 30) * 1000;
  })();
  const env = {
    ENTRY: JSON.stringify({ key: 'm1-c1', model: 'm-one', case: 'c1', first_for_model: true, base: SHA_A, head: SHA_B }),
    API_BASE: 'https://gw.example/compat',
    AUTH_TOKEN: 'placeholder-bearer',
    EXTRA_BODY: '{"stream": true}',
    BACKEND: 'cf-ai-gateway',
    EXTRA_HEADERS: 'H=v',
    SUBJECT_DIR: '/w/subject',
    OUT_DIR: '/w/out',
    JOB_STARTED: '1000',
    PROBE_STARTED: '1010',
    PROBE_ENDED: '1051',
    JOB_BUDGET_SECONDS: '480',
    PATH: '/bin',
    HOME: '/h',
  };
  const code = await runReview({ env, casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }), run, now, step });
  assert.equal(code, 0);
  const sets = calls.filter((c) => c.argv[0] === 'config').map((c) => c.argv.slice(1));
  // The base, bearer and body are the Credentials step's (the backend's
  // profile, Issue#481), never a copy the bake-off keeps.
  assert.ok(sets.some((a) => a[0] === 'set' && a[1] === 'llm.url' && a[2] === 'https://gw.example/compat'));
  assert.ok(sets.some((a) => a[1] === 'llm.model' && a[2] === 'm-one'));
  assert.ok(sets.some((a) => a[1] === 'llm.protocol' && a[2] === 'openai'));
  assert.ok(sets.some((a) => a[1] === 'llm.extra_body' && a[2] === '{"stream": true}'));
  const review = calls.find((c) => c.argv[0] === 'review');
  assert.equal(review.cwd, '/w/subject');
  assert.equal(review.env.OCR_LLM_EXTRA_HEADERS, 'H=v');
  assert.equal(review.env.OCR_NO_UPDATE, '1');
  assert.equal(review.env.OCR_LLM_TIMEOUT, '300');
  assert.equal(review.env.OCR_LLM_TOKEN, 'placeholder-bearer');
  assert.ok(review.deadlineMs > 0 && review.deadlineMs <= 480 * 1000, 'the deadline is what is left of the job budget');
  const rec = JSON.parse(step.files['/w/out/record.json']);
  assert.equal(rec.outcome, 'complete');
  assert.equal(rec.backend, 'cf-ai-gateway');
  assert.equal(rec.probe_seconds, 41);
  assert.deepEqual(rec.located, [true]);
  assert.ok(step.files['/w/out/ocr-result.json']);
});

test('review step: a failed probe is a probe-failed record, and ocr never runs', async () => {
  const step = fakeStep();
  let ran = false;
  const code = await runReview({
    env: {
      ENTRY: JSON.stringify({ key: 'k', model: 'm', case: 'c1', first_for_model: true, base: SHA_A, head: SHA_B }),
      PROBE_OUTCOME: 'failure',
      PROBE_CAUSE: 'cold-model',
      PROBE_STARTED: '100',
      PROBE_ENDED: '460',
      OUT_DIR: '/o',
      JOB_STARTED: '0',
      JOB_BUDGET_SECONDS: '480',
    },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    run: async () => {
      ran = true;
      return { code: 0 };
    },
    now: () => 0,
    step,
  });
  assert.equal(code, 0);
  assert.equal(ran, false);
  const rec = JSON.parse(step.files['/o/record.json']);
  assert.equal(rec.outcome, 'probe-failed');
  assert.match(rec.detail, /cold-model/);
  assert.equal(rec.probe_seconds, 360);
});

test('collate step: no records directory (every run died before uploading) is all no-record, not an error', () => {
  const step = fakeStep();
  let summary = '';
  const code = runCollate({
    env: { RECORDS_DIR: join(tmpdir(), 'bakeoff-absent-dir-for-test'), MODELS: 'a', CASES: '', OUT_DIR: '/o' },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    step,
    summary: (t) => {
      summary += t;
    },
  });
  assert.equal(code, 0);
  assert.match(summary, /no-record 1/);
});

test('review step: a step before the probe failed (the probe skipped) is setup-failed, not probe-failed', async () => {
  const step = fakeStep();
  const code = await runReview({
    env: {
      ENTRY: JSON.stringify({ key: 'k', model: 'm', case: 'c1', first_for_model: false, base: SHA_A, head: SHA_B }),
      PROBE_OUTCOME: 'skipped',
      PROBE_CAUSE: '',
      OUT_DIR: '/o',
      JOB_STARTED: '0',
      JOB_BUDGET_SECONDS: '480',
    },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    run: async () => ({ code: 0 }),
    now: () => 0,
    step,
  });
  assert.equal(code, 0);
  assert.equal(JSON.parse(step.files['/o/record.json']).outcome, 'setup-failed');
});

test('review step: an ocr config call that fails or hangs is engine-error naming the setting, never "exited null"', async () => {
  for (const [answer, why] of [
    [{ code: null, timedOut: true, stdout: '' }, /llm\.url.*timed out/],
    [{ code: 2, timedOut: false, stdout: '' }, /llm\.url.*exited 2/],
  ]) {
    const step = fakeStep();
    const run = async (_cmd, argv) => (argv[2] === 'llm.url' ? answer : { code: 0, timedOut: false, stdout: '' });
    const code = await runReview({
      env: {
        ENTRY: JSON.stringify({ key: 'k', model: 'm', case: 'c1', first_for_model: false, base: SHA_A, head: SHA_B }),
        PROBE_OUTCOME: 'success',
        GATEWAY_URL: 'https://gw',
        OUT_DIR: '/o',
        JOB_STARTED: '0',
        JOB_BUDGET_SECONDS: '480',
      },
      casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
      run,
      now: () => 0,
      step,
    });
    assert.equal(code, 0);
    const rec = JSON.parse(step.files['/o/record.json']);
    assert.equal(rec.outcome, 'engine-error');
    assert.match(rec.detail, why);
  }
});

test('review step: a case id the cases file lacks fails before ocr runs', async () => {
  const step = fakeStep();
  let ran = false;
  const code = await runReview({
    env: { ENTRY: JSON.stringify({ key: 'k', model: 'm', case: 'nope', base: SHA_A, head: SHA_B }), OUT_DIR: '/o', JOB_STARTED: '0', JOB_BUDGET_SECONDS: '480' },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    run: async () => {
      ran = true;
      return { code: 0 };
    },
    now: () => 0,
    step,
  });
  assert.equal(code, 1);
  assert.equal(ran, false);
});

test('review step: a failed review still writes its record, and the step does not fail the job', async () => {
  const step = fakeStep();
  const run = async (_cmd, argv) => (argv[0] === 'review' ? { code: null, timedOut: true, stdout: '' } : { code: 0, stdout: '' });
  const code = await runReview({
    env: {
      ENTRY: JSON.stringify({ key: 'k', model: 'm', case: 'c1', first_for_model: false, base: SHA_A, head: SHA_B }),
      GATEWAY_URL: 'https://gw',
      SUBJECT_DIR: '/s',
      OUT_DIR: '/o',
      JOB_STARTED: '0',
      PROBE_STARTED: '0',
      PROBE_ENDED: '0',
      JOB_BUDGET_SECONDS: '480',
    },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    run,
    now: () => 10_000,
    step,
  });
  assert.equal(code, 0);
  assert.equal(JSON.parse(step.files['/o/record.json']).outcome, 'timeout');
});

test('collate step: reads every record under the directory and writes the report and the combined results', () => {
  const dir = mkdtempSync(join(tmpdir(), 'bakeoff-'));
  mkdirSync(join(dir, 'bakeoff-m1-c1'));
  writeFileSync(
    join(dir, 'bakeoff-m1-c1', 'record.json'),
    JSON.stringify({ record_version: 1, key: 'm1-c1', model: 'a', case: 'c1', outcome: 'complete', located: [true], findings_total: 1, probe_seconds: 1, review_seconds: 2, cold: true }),
  );
  const step = fakeStep();
  let summary = '';
  const code = runCollate({
    env: { RECORDS_DIR: dir, MODELS: 'a\nb', CASES: '', OUT_DIR: '/o' },
    casesText: JSON.stringify({ cases: [kase({ id: 'c1' })] }),
    step,
    summary: (t) => {
      summary += t;
    },
  });
  assert.equal(code, 0);
  assert.match(summary, /\| a \| 1 \| 1 \|/);
  assert.match(summary, /m2-c1/);
  const combined = JSON.parse(step.files['/o/bakeoff-results.json']);
  assert.equal(combined.records.length, 1);
  assert.deepEqual(combined.missing, ['m2-c1']);
});

// --- The workflow file ------------------------------------------------------

const WORKFLOW = readFileSync(join(ROOT, '.github/workflows/ocr-bakeoff.yml'), 'utf8');
const CALLER = readFileSync(join(ROOT, 'docs/ocr-bakeoff-caller.yml'), 'utf8');
const code = (text) =>
  text
    .split('\n')
    .filter((l) => !/^\s*#/.test(l))
    .join('\n');

test('workflow: reusable only, and every job refuses any trigger but a dispatch', () => {
  assert.match(code(WORKFLOW), /^on:\n {2}workflow_call:/m);
  const jobs = code(WORKFLOW).split('\njobs:\n')[1].split(/\n(?= {2}[a-z-]+:\n)/);
  assert.ok(jobs.length >= 3);
  for (const job of jobs) assert.match(job, /if: .*github\.event_name == 'workflow_dispatch'/, job.split('\n')[0]);
});

test('workflow: runs on the caller pool, one job at a time, never failing fast, under the pool ceiling', () => {
  const body = code(WORKFLOW);
  assert.ok(body.includes(`runs-on: \${{ fromJSON(vars.CI_RUNS_ON || '"ubuntu-latest"') }}`));
  assert.match(body, /max-parallel: 1\b/);
  assert.match(body, /fail-fast: false/);
  for (const m of body.matchAll(/timeout-minutes: (\d+)/g)) assert.ok(Number(m[1]) <= 9, `timeout-minutes ${m[1]}`);
});

test('workflow: the secret is read in exactly one step, and every action is pinned by SHA', () => {
  const body = code(WORKFLOW);
  assert.equal(body.match(/secrets\.OLLAMA_GATEWAY_OP_SA_TOKEN/g).length, 1);
  for (const m of body.matchAll(/uses: (\S+)/g)) assert.match(m[1], /@[0-9a-f]{40}$/, m[1]);
});

/** The text of every run: block, single line or block scalar. */
function runBlocks(text) {
  const all = text.split('\n');
  const out = [];
  all.forEach((l, i) => {
    const m = l.match(/^(\s*)(- )?run:\s*(.*)$/);
    // A step's run: (a list item, or a key under one); not a job named run.
    if (!m || (!m[2] && m[1].length < 8)) return;
    const own = m[1].length + (m[2] ? 2 : 0);
    if (m[3] && !/^[|>][-+]?$/.test(m[3].trim())) return out.push(m[3]);
    const body = [];
    for (const next of all.slice(i + 1)) {
      if (next.trim() !== '' && next.match(/^ */)[0].length <= own) break;
      body.push(next);
    }
    out.push(body.join('\n'));
  });
  return out;
}

test('workflow: no matrix value or input is interpolated into a run: block', () => {
  const runs = runBlocks(code(WORKFLOW));
  assert.ok(runs.length >= 3);
  for (const r of runs) assert.doesNotMatch(r, /\$\{\{\s*(matrix|inputs)\./, r);
});

test('workflow: nothing ocr writes to stderr is uploaded', () => {
  assert.doesNotMatch(code(WORKFLOW), /stderr/);
});

test('workflow: ocr is the version and the settings OCR on Demand runs, so a bake-off measures production', () => {
  const review = readFileSync(join(ROOT, '.github/workflows/ocr-review.yml'), 'utf8');
  const pin = review.match(/ocr_version: '([^']+)'/)[1];
  assert.equal(code(WORKFLOW).match(/OCR_VERSION: '([^']+)'/)[1], pin);
  // Both take the protocol and auth header from the Credentials step.
  assert.match(review, /llm_protocol: \$\{\{ steps\.creds\.outputs\.protocol \}\}/);
  assert.match(review, /llm_auth_header: \$\{\{ steps\.creds\.outputs\.auth_header \}\}/);
  assert.match(code(WORKFLOW), /PROTOCOL: \$\{\{ steps\.creds\.outputs\.protocol \}\}/);
  assert.match(code(WORKFLOW), /AUTH_HEADER: \$\{\{ steps\.creds\.outputs\.auth_header \}\}/);
  for (const v of ['ANTHROPIC_OP_ITEM', 'ANTHROPIC_URL', 'ANTHROPIC_MODEL']) assert.match(code(WORKFLOW), new RegExp(`${v}: \\$\\{\\{ vars\\.${v} \\}\\}`), v);
});

test('caller: dispatch only, passes the one secret by name, pins workflow and tools_ref to one SHA', () => {
  const body = code(CALLER);
  assert.match(body, /^on:\n {2}workflow_dispatch:/m);
  assert.doesNotMatch(body, /issue_comment|pull_request|push:|schedule:/);
  assert.doesNotMatch(body, /secrets: inherit/);
  const pin = body.match(/ocr-bakeoff\.yml@([0-9a-f]{40})/)[1];
  assert.equal(body.match(/tools_ref: '([0-9a-f]{40})'/)[1], pin);
});

test('workflow: the backend input reaches the Credentials step as a dispatch override, with both backends\' variables (Issue#481)', () => {
  const body = code(WORKFLOW);
  assert.match(body, /BACKEND_OVERRIDE:\s*\$\{\{\s*inputs\.backend\s*\}\}/);
  for (const v of ['OCR_BACKEND', 'CF_AI_GATEWAY_OP_ITEM', 'CF_AI_GATEWAY_URL', 'CF_AI_GATEWAY_MODEL', 'CF_AI_GATEWAY_REASONING']) {
    assert.match(body, new RegExp(`${v}:\\s*\\$\\{\\{\\s*vars\\.${v}\\s*\\}\\}`), v);
  }
  for (const [env, out] of [['API_BASE', 'api_base'], ['AUTH_TOKEN', 'auth_token'], ['EXTRA_BODY', 'extra_body'], ['BACKEND', 'backend']]) {
    assert.match(body, new RegExp(`${env}:\\s*\\$\\{\\{\\s*steps\\.creds\\.outputs\\.${out}\\s*\\}\\}`), env);
  }
  assert.match(code(CALLER), /backend:\s*\$\{\{\s*inputs\.backend\s*\}\}/);
});

test('configArgs: the protocol and auth header follow the backend; empty is openai with the default header', () => {
  const setting = (args, key) => args.find((a) => a[1] === 'set' && a[2] === key)[3];
  const openai = configArgs({ apiBase: 'https://g/v1', model: 'm', extraBody: '{}' });
  assert.equal(setting(openai, 'llm.protocol'), 'openai');
  assert.equal(setting(openai, 'llm.use_anthropic'), 'false');
  assert.equal(setting(openai, 'llm.auth_header'), '');
  const anthropic = configArgs({ apiBase: 'https://api.anthropic.com', model: 'claude-sonnet-5-5', extraBody: '{}', protocol: 'anthropic', authHeader: 'x-api-key' });
  assert.equal(setting(anthropic, 'llm.protocol'), 'anthropic');
  assert.equal(setting(anthropic, 'llm.use_anthropic'), 'true');
  assert.equal(setting(anthropic, 'llm.auth_header'), 'x-api-key');
});
