// test/ocr_review_workflow.test.mjs -- OCR on Demand, the workflow files'
// security and wiring properties (docs/design/OCR-ON-DEMAND.DESIGN.md:
// Caller workflow, Reusable workflow, Security Considerations; Key
// Decisions, runner row). Read as text: what a reviewer would check by eye,
// made mechanical. No network.
// Run: node --test test/ocr_review_workflow.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { AUTHORIZE_STEPS, REVIEW_STEPS } from '../bin/ocr-review';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const REUSABLE = readFileSync(join(ROOT, '.github/workflows/ocr-review.yml'), 'utf8');
const CALLER = readFileSync(join(ROOT, 'docs/ocr-review-caller.yml'), 'utf8');

const SHA = /^[0-9a-f]{40}$/;
const RUNS_ON = `runs-on: \${{ fromJSON(vars.CI_RUNS_ON || '"ubuntu-latest"') }}`;

// --- A minimal indentation reader --------------------------------------------

const lines = (text) => text.split('\n').filter((l) => !/^\s*#/.test(l));
const indentOf = (line) => line.match(/^ */)[0].length;

/** The lines under `key:` at `indent`, until the next line at or above it. */
function block(text, key, indent = 0) {
  const all = lines(text);
  const start = all.findIndex((l) => indentOf(l) === indent && l.trim().startsWith(`${key}:`));
  if (start < 0) return null;
  const out = [];
  for (const l of all.slice(start + 1)) {
    if (l.trim() !== '' && indentOf(l) <= indent) break;
    out.push(l);
  }
  return out.join('\n');
}

/** The keys directly under a block at `indent`. */
const keysAt = (body, indent) =>
  lines(body ?? '')
    .filter((l) => indentOf(l) === indent && /^\s*[A-Za-z0-9_-]+:/.test(l))
    .map((l) => l.trim().split(':')[0]);

const jobsOf = (text) => keysAt(block(text, 'jobs'), 2);
const jobBlock = (text, job) => block(block(text, 'jobs'), job, 2);

/** The text of every run: block (single line or block scalar). */
function runBlocks(text) {
  const all = text.split('\n');
  const out = [];
  all.forEach((l, i) => {
    const m = l.match(/^(\s*)(- )?run:\s*(.*)$/);
    if (!m) return;
    const own = m[1].length + (m[2] ? 2 : 0);
    if (m[3] && !/^[|>][-+]?$/.test(m[3].trim())) {
      out.push(m[3]);
      return;
    }
    const body = [];
    for (const next of all.slice(i + 1)) {
      if (next.trim() !== '' && indentOf(next) <= own) break;
      body.push(next);
    }
    out.push(body.join('\n'));
  });
  return out;
}

const permissionLines = (body) =>
  lines(body ?? '')
    .map((l) => l.trim())
    .filter(Boolean)
    .sort();

const EXACT_PERMISSIONS = ['contents: read', 'issues: write', 'pull-requests: write'];

// --- Caller --------------------------------------------------------------------

test('caller: triggers are workflow_dispatch (pr, model) and issue_comment created, nothing else', () => {
  assert.deepEqual(keysAt(block(CALLER, 'on'), 2).sort(), ['issue_comment', 'workflow_dispatch']);
  assert.match(block(block(CALLER, 'on'), 'issue_comment', 2), /types:\s*\[created\]/);
  const inputs = keysAt(block(block(block(CALLER, 'on'), 'workflow_dispatch', 2), 'inputs', 4), 6);
  assert.deepEqual(inputs.sort(), ['model', 'pr']);
});

test('caller: permissions are exactly contents read, pull-requests write, issues write', () => {
  assert.deepEqual(permissionLines(block(CALLER, 'permissions')), EXACT_PERMISSIONS);
});

test('caller: one job, using the reusable workflow pinned by a commit SHA, with tools_ref at the same SHA', () => {
  assert.equal(jobsOf(CALLER).length, 1);
  const uses = CALLER.match(/uses:\s*9atatimer\/tds-utils\/\.github\/workflows\/ocr-review\.yml@(\S+)/);
  assert.ok(uses, 'uses the tds-utils reusable workflow');
  assert.match(uses[1], SHA);
  const toolsRef = CALLER.match(/tools_ref:\s*'?([0-9a-f]+)'?/);
  assert.ok(toolsRef, 'passes tools_ref');
  assert.equal(toolsRef[1], uses[1]);
});

test('caller: passes exactly one secret, by name, and never inherits', () => {
  assert.doesNotMatch(CALLER, /inherit/);
  const refs = CALLER.match(/secrets\.[A-Za-z0-9_]+/g) ?? [];
  assert.deepEqual(refs, ['secrets.OLLAMA_GATEWAY_OP_SA_TOKEN']);
  assert.match(CALLER, /OLLAMA_GATEWAY_OP_SA_TOKEN:\s*\$\{\{\s*secrets\.OLLAMA_GATEWAY_OP_SA_TOKEN\s*\}\}/);
});

test('caller: the model reaches the reusable workflow on a dispatch only', () => {
  assert.match(CALLER, /model:\s*\$\{\{\s*github\.event_name == 'workflow_dispatch' && inputs\.model \|\| ''\s*\}\}/);
});

// --- Reusable workflow: shape ----------------------------------------------------

test('reusable: workflow_call only, with pr, model, tools_ref and the one secret', () => {
  assert.deepEqual(keysAt(block(REUSABLE, 'on'), 2), ['workflow_call']);
  const call = block(block(REUSABLE, 'on'), 'workflow_call', 2);
  assert.deepEqual(keysAt(block(call, 'inputs', 4), 6).sort(), ['model', 'pr', 'tools_ref']);
  assert.deepEqual(keysAt(block(call, 'secrets', 4), 6), ['OLLAMA_GATEWAY_OP_SA_TOKEN']);
});

test('reusable: permissions are exactly the three, and no job widens them', () => {
  assert.deepEqual(permissionLines(block(REUSABLE, 'permissions')), EXACT_PERMISSIONS);
  for (const job of jobsOf(REUSABLE)) assert.equal(block(jobBlock(REUSABLE, job), 'permissions', 4), null, `${job} sets no permissions`);
});

test('reusable: exactly the authorize, review and report jobs', () => {
  assert.deepEqual(jobsOf(REUSABLE), ['authorize', 'review', 'report']);
});

test('reusable: every job runs on the caller\'s CI_RUNS_ON when set, else GitHub-hosted', () => {
  for (const job of jobsOf(REUSABLE)) assert.ok(jobBlock(REUSABLE, job).includes(RUNS_ON), job);
});

test('reusable: every job times out under the runner pool\'s 10-minute container ceiling', () => {
  for (const job of jobsOf(REUSABLE)) {
    const m = jobBlock(REUSABLE, job).match(/timeout-minutes:\s*(\d+)/);
    assert.ok(m, `${job} has timeout-minutes`);
    assert.ok(Number(m[1]) < 10, `${job}: ${m[1]} < 10`);
  }
});

test('reusable: every action is pinned by a full commit SHA', () => {
  const uses = [...REUSABLE.matchAll(/uses:\s*([^\s#]+)/g)].map((m) => m[1]);
  assert.ok(uses.length > 0);
  for (const u of uses) assert.match(u.split('@')[1] ?? '', SHA, u);
});

test('reusable: no run: block interpolates an expression', () => {
  for (const body of runBlocks(REUSABLE)) assert.doesNotMatch(body, /\$\{\{/, body.slice(0, 200));
});

// --- Reusable workflow: secret isolation and gating -------------------------------

test('reusable: authorize and report reference no secret', () => {
  for (const job of ['authorize', 'report']) assert.doesNotMatch(jobBlock(REUSABLE, job), /secrets\./, job);
});

test('reusable: only the review job references the secret, and only in the Credentials step', () => {
  const review = jobBlock(REUSABLE, 'review');
  assert.equal((review.match(/secrets\.OLLAMA_GATEWAY_OP_SA_TOKEN/g) ?? []).length, 1);
  const credentials = review.split(/\n\s*- name: /).find((s) => s.startsWith('Credentials'));
  assert.ok(credentials && /secrets\.OLLAMA_GATEWAY_OP_SA_TOKEN/.test(credentials));
});

test('reusable: review runs only on the authorize job\'s approval', () => {
  const review = jobBlock(REUSABLE, 'review');
  assert.match(review, /needs:\s*\[?authorize\]?/);
  assert.match(review, /if:\s*needs\.authorize\.outputs\.decision == 'approve'/);
});

test('reusable: report runs after both, whatever their outcome, unless the run was skipped', () => {
  const report = jobBlock(REUSABLE, 'report');
  assert.match(report, /needs:\s*\[authorize, review\]/);
  const cond = report.match(/^\s{4}if:\s*(.+)$/m)?.[1] ?? '';
  assert.match(cond, /always\(\)/);
  assert.match(cond, /needs\.authorize\.result != 'skipped'/);
  assert.match(cond, /needs\.authorize\.outputs\.decision != 'skip'/);
});

test('reusable: the record is uploaded before the summary comment is posted', () => {
  const report = jobBlock(REUSABLE, 'report');
  const upload = report.indexOf('name: Upload the run record');
  const comment = report.indexOf('name: Post the summary comment');
  assert.ok(upload > 0 && comment > upload);
});

// --- Reusable workflow: the review step -------------------------------------------

test('reusable: the upstream action is pinned by SHA with an exact ocr_version, no self-update, no telemetry', () => {
  const review = jobBlock(REUSABLE, 'review');
  assert.match(review, /uses:\s*alibaba\/open-code-review@[0-9a-f]{40}/);
  assert.match(review, /ocr_version:\s*'?\d+\.\d+\.\d+'?\s*$/m);
  assert.match(review, /OCR_NO_UPDATE:\s*'1'/);
  assert.match(review, /OCR_ENABLE_TELEMETRY:\s*'0'/);
  assert.match(review, /stream_progress:\s*'false'/);
  assert.match(review, /pr_number:\s*\$\{\{\s*needs\.authorize\.outputs\.pr\s*\}\}/);
  assert.match(review, /head_sha:\s*\$\{\{\s*needs\.authorize\.outputs\.head_sha\s*\}\}/);
  assert.match(review, /base_ref:\s*\$\{\{\s*needs\.authorize\.outputs\.base_ref\s*\}\}/);
});

test('reusable: the job outputs and step names match the report\'s step tables', () => {
  for (const [job, table] of [
    ['authorize', AUTHORIZE_STEPS],
    ['review', REVIEW_STEPS],
  ]) {
    const body = jobBlock(REUSABLE, job);
    const outputs = keysAt(block(body, 'outputs', 4), 6);
    for (const { key, name, cause, detail } of table) {
      assert.ok(body.includes(`- name: ${name}\n`), `${job} has step "${name}"`);
      assert.ok(outputs.includes(key), `${job} outputs ${key}`);
      if (cause) assert.ok(outputs.includes(cause) && outputs.includes(detail), `${job} outputs ${cause} and ${detail}`);
    }
  }
});

test('reusable: no job output carries the gateway headers', () => {
  for (const job of jobsOf(REUSABLE)) assert.doesNotMatch(block(jobBlock(REUSABLE, job), 'outputs', 4) ?? '', /extra_headers|headers_file/);
});
