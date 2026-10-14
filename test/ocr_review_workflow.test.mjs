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

test('caller: triggers are workflow_dispatch (pr, model, backend) and issue_comment created, nothing else', () => {
  assert.deepEqual(keysAt(block(CALLER, 'on'), 2).sort(), ['issue_comment', 'workflow_dispatch']);
  assert.match(block(block(CALLER, 'on'), 'issue_comment', 2), /types:\s*\[created\]/);
  const inputs = keysAt(block(block(block(CALLER, 'on'), 'workflow_dispatch', 2), 'inputs', 4), 6);
  assert.deepEqual(inputs.sort(), ['backend', 'model', 'pr']);
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

test('caller: the backend reaches the reusable workflow on a dispatch only (Issue#481)', () => {
  assert.match(CALLER, /backend:\s*\$\{\{\s*github\.event_name == 'workflow_dispatch' && inputs\.backend \|\| ''\s*\}\}/);
});

// --- Reusable workflow: shape ----------------------------------------------------

test('reusable: workflow_call only, with pr, model, backend, tools_ref and the one secret', () => {
  assert.deepEqual(keysAt(block(REUSABLE, 'on'), 2), ['workflow_call']);
  const call = block(block(REUSABLE, 'on'), 'workflow_call', 2);
  assert.deepEqual(keysAt(block(call, 'inputs', 4), 6).sort(), ['backend', 'model', 'pr', 'tools_ref']);
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

test('reusable: the Review step takes the API base, bearer and body from the Credentials step (Issue#479, Issue#481)', () => {
  const review = jobBlock(REUSABLE, 'review');
  // The body (reasoning off on ollama) and the bearer are the backend's
  // profile in lib/ocr-review/gateway.mjs, tested there; the workflow only
  // forwards them, so no backend's literal lives here.
  assert.match(review, /llm_url:\s*\$\{\{\s*steps\.creds\.outputs\.api_base\s*\}\}\s*$/m);
  assert.match(review, /llm_auth_token:\s*\$\{\{\s*steps\.creds\.outputs\.auth_token\s*\}\}\s*$/m);
  assert.match(review, /llm_extra_body:\s*\$\{\{\s*steps\.creds\.outputs\.extra_body\s*\}\}\s*$/m);
});

test('reusable: the Credentials step gets the backend selector, its dispatch override and both backends\' variables', () => {
  const review = jobBlock(REUSABLE, 'review');
  for (const v of ['OCR_BACKEND', 'CF_AI_GATEWAY_OP_ITEM', 'CF_AI_GATEWAY_URL', 'CF_AI_GATEWAY_MODEL', 'CF_AI_GATEWAY_REASONING', 'OLLAMA_GATEWAY_OP_ITEM', 'OLLAMA_GATEWAY_URL', 'OLLAMA_GATEWAY_MODEL']) {
    assert.match(review, new RegExp(`${v}:\\s*\\$\\{\\{\\s*vars\\.${v}\\s*\\}\\}`), v);
  }
  assert.match(review, /BACKEND_OVERRIDE:\s*\$\{\{\s*inputs\.backend\s*\}\}/);
  assert.match(review, /API_BASE:\s*\$\{\{\s*steps\.creds\.outputs\.api_base\s*\}\}/);
  assert.match(review, /BACKEND:\s*\$\{\{\s*steps\.creds\.outputs\.backend\s*\}\}/);
  assert.match(block(review, 'outputs', 4), /backend:\s*\$\{\{\s*steps\.creds\.outputs\.backend\s*\}\}/);
});

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

test('reusable: the verdict step gets the action\'s post counts through env:, from the Review step\'s outputs', () => {
  const review = jobBlock(REUSABLE, 'review');
  const verdict = review.split(/\n\s*- name: /).find((s) => s.startsWith('Verdict\n'));
  assert.ok(verdict, 'review has a Verdict step');
  const env = block(verdict, 'env', 8) ?? '';
  for (const count of ['total', 'inline', 'routed', 'skipped', 'failed']) {
    const name = `OCR_COMMENTS_${count.toUpperCase()}`;
    assert.match(env, new RegExp(`^\\s+${name}:\\s*\\$\\{\\{\\s*steps\\.ocr\\.outputs\\.comments_${count}\\s*\\}\\}\\s*$`, 'm'), name);
  }
});

test('reusable: the review job hands upstream\'s summary_comment_url to the report as upstream_summary_url', () => {
  const outputs = block(jobBlock(REUSABLE, 'review'), 'outputs', 4) ?? '';
  assert.match(outputs, /^\s+upstream_summary_url:\s*\$\{\{\s*steps\.ocr\.outputs\.summary_comment_url\s*\}\}\s*$/m);
});

// --- Reusable workflow: host tools (tds-utils#446) ------------------------------

const reviewSteps = () =>
  jobBlock(REUSABLE, 'review')
    .split(/\n\s*- name: /)
    .slice(1);
const stepNamed = (name) => reviewSteps().find((s) => s.startsWith(`${name}\n`));

test('reusable: the review job checks its host tools before installing op and before any credential', () => {
  const check = stepNamed('Check the host tools');
  assert.ok(check, 'review has a Check the host tools step');
  assert.match(check, /^\s+id: hosttools$/m);
  assert.match(check, /^\s+run: node "\$RUNNER_TEMP\/ocr-review-tools\/bin\/ocr-review" host-tools$/m);
  assert.doesNotMatch(check, /secrets\.|vars\./);
  const names = reviewSteps().map((s) => s.split('\n')[0]);
  const at = (name) => names.indexOf(name);
  assert.ok(at('Check the host tools') > at('Stage the tools'), 'after the tools are staged');
  assert.ok(at('Check the host tools') < at('Install the 1Password CLI'), 'before the install');
  assert.ok(at('Install the 1Password CLI') < at('Credentials'), 'the install still precedes credentials');
});

test('reusable: the 1Password CLI is installed only when the check says op is not on the runner', () => {
  const install = stepNamed('Install the 1Password CLI');
  assert.ok(install);
  assert.match(install, /^\s+if: steps\.hosttools\.outputs\.install_op == 'true'$/m);
  assert.match(install, /uses:\s*1password\/install-cli-action@[0-9a-f]{40}/);
});

test('reusable: the report reads the host-tools step, its cause and detail, from the review job', () => {
  const at = (key) => REVIEW_STEPS.findIndex((s) => s.key === key);
  const check = REVIEW_STEPS[at('hosttools')];
  assert.deepEqual(check, { key: 'hosttools', name: 'Check the host tools', cause: 'hosttools_cause', detail: 'hosttools_detail' });
  assert.ok(at('stage') < at('hosttools') && at('hosttools') < at('opcli'), 'the table keeps the workflow order');
  const outputs = block(jobBlock(REUSABLE, 'review'), 'outputs', 4) ?? '';
  assert.match(outputs, /^\s+hosttools_cause:\s*\$\{\{\s*steps\.hosttools\.outputs\.cause\s*\}\}\s*$/m);
  assert.match(outputs, /^\s+hosttools_detail:\s*\$\{\{\s*steps\.hosttools\.outputs\.detail\s*\}\}\s*$/m);
});

// --- Reusable workflow: reactions on the /ocr comment -------------------------

const stepOf = (job, name) =>
  jobBlock(REUSABLE, job)
    .split(/\n\s*- name: /)
    .find((s) => s.startsWith(`${name}\n`));
const stepNames = (job) =>
  jobBlock(REUSABLE, job)
    .split(/\n\s*- name: /)
    .slice(1)
    .map((s) => s.split('\n')[0]);

test('reusable: the authorize job acknowledges an approved comment after deciding, and the ack cannot fail the run', () => {
  const ack = stepOf('authorize', 'Acknowledge the comment');
  assert.ok(ack, 'authorize has an Acknowledge the comment step');
  assert.match(ack, /^\s+id: ack$/m);
  assert.match(ack, /^\s+continue-on-error: true$/m);
  assert.match(ack, /^\s+run: node \.ocr-review-tools\/bin\/ocr-review ack$/m);
  assert.match(ack, /^\s+COMMENT_ID: \$\{\{ github\.event\.comment\.id \}\}$/m);
  assert.match(ack, /^\s+DECISION: \$\{\{ steps\.authorize\.outputs\.decision \}\}$/m);
  assert.match(ack, /^\s+GITHUB_TOKEN: \$\{\{ github\.token \}\}$/m);
  const names = stepNames('authorize');
  assert.ok(names.indexOf('Acknowledge the comment') > names.indexOf('Authorize'));
  const outputs = block(jobBlock(REUSABLE, 'authorize'), 'outputs', 4) ?? '';
  assert.match(outputs, /^\s+ack_reaction_id:\s*\$\{\{\s*steps\.ack\.outputs\.reaction_id\s*\}\}\s*$/m);
});

test('reusable: after the summary comment, the report replaces eyes with the outcome, and that cannot fail the run', () => {
  const react = stepOf('report', 'React with the outcome');
  assert.ok(react, 'report has a React with the outcome step');
  assert.match(react, /^\s+continue-on-error: true$/m);
  assert.match(react, /^\s+if: always\(\) && steps\.record\.outcome == 'success'$/m);
  assert.match(react, /^\s+run: node \.ocr-review-tools\/bin\/ocr-review react$/m);
  assert.match(react, /^\s+COMMENT_ID: \$\{\{ github\.event\.comment\.id \}\}$/m);
  assert.match(react, /^\s+OUTCOME: \$\{\{ steps\.record\.outputs\.outcome \}\}$/m);
  assert.match(react, /^\s+ACK_REACTION_ID: \$\{\{ needs\.authorize\.outputs\.ack_reaction_id \}\}$/m);
  const names = stepNames('report');
  assert.ok(names.indexOf('React with the outcome') > names.indexOf('Post the summary comment'));
});
